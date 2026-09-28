"""Chat confirmation, contact recovery and returning-patient actions.

This flow does not prove email ownership. Deploy behind real authentication
before allowing access to real patient records.
"""
from domain.models import PatientUpdate
from tools.patients import read, recovery_candidate, replace_contacts
from tools.history import patient_bookings, all_clinics
from .. import replies
from ..contacts import read_contacts
from services.contact_input import error_reply, observed_contacts, validate_contact_values
from ..answers import is_yes
from ..conversation import Context, RECOVERY, CONTACT_CONFIRM, REGISTRY, MENU, COMPLAINT
from ..prompts import UPDATE


def begin_confirmation(context: Context, patient_id: int, purpose: str) -> str:
    """Read back details in chat. Never send, request, or accept an email code."""
    flow = context.flow
    flow.recovery_patient_id = patient_id
    flow.verification_purpose = purpose  # Compatibility with older in-memory flows.
    flow.challenge, flow.contact_fingerprint = None, None
    flow.patient, flow.verified = None, False
    patient = read(patient_id)
    if not patient:
        flow.step = RECOVERY
        return "The account could not be found. Please contact the clinic."

    if purpose == "recovery":
        if not all(flow.contact_update.get(k) for k in ("email", "phone")):
            flow.step = RECOVERY
            return "Please provide both the updated email address and phone number."
        # Optimistic concurrency protection stays in the atomic repository write.
        flow.contact_fingerprint = (patient["email"], patient["phone"])
        flow.step = CONTACT_CONFIRM
        return confirm_contacts(flow.contact_update)

    flow.patient, flow.returning = patient, True
    # Finding matching contacts is not confirmation. The registry's explicit
    # yes/confirmation path enables account actions; history is blocked until then.
    flow.step = REGISTRY
    return replies.on_file(patient)


def begin_verification(context: Context, patient_id: int, purpose: str) -> str:
    """Backward-compatible entry point; now performs only chat confirmation."""
    return begin_confirmation(context, patient_id, purpose)


def verify(context: Context, message: str) -> str:
    """Recover a legacy VERIFY state without ever interpreting an OTP."""
    flow = context.flow
    return begin_confirmation(context, flow.recovery_patient_id, flow.verification_purpose)


def collect_contacts(context: Context, message: str) -> str:
    flow = context.flow
    found = read_contacts(context, PatientUpdate, UPDATE, {"message": message}, "Read the updated email and phone")
    flow.contact_update.update({key: value for key, value in found.values.items() if key in {"email", "phone"}})
    for field in found.errors:
        flow.contact_update.pop(field, None)
    if flow.contact_errors:
        return error_reply(flow.contact_errors)
    if not all(flow.contact_update.get(k) for k in ("email", "phone")):
        return "Please provide both the updated email address and phone number. Neither will be changed until you confirm them in this chat."
    flow.editing = None
    return begin_confirmation(context, flow.recovery_patient_id, "recovery")


def recover_identity(context: Context, message: str) -> str:
    found = validate_contact_values(observed_contacts(message), message)
    if found.errors:
        return error_reply(found.errors)
    email = found.values.get("email")
    patient_id = recovery_candidate(email) if email else None
    if patient_id is None:
        return "I could not locate an account with those details. Provide the email currently on file, or contact the clinic for recovery."
    context.flow.recovery_patient_id = patient_id
    context.flow.step = RECOVERY
    return replies.contact_mismatch()


def confirm_contacts(changes: dict) -> str:
    return (f"Update the email to {changes['email']} and the phone to {changes['phone']}? "
            "Reply yes to save both, or provide corrected contact details. Nothing has been changed yet.")


def save_contacts(context: Context, message: str) -> str:
    flow = context.flow
    if flow.step != CONTACT_CONFIRM or flow.recovery_patient_id is None:
        return "Please provide the email currently on file and both updated contact details first."
    if not all(flow.contact_update.get(k) for k in ("email", "phone")):
        flow.step = RECOVERY
        return "Please provide both the updated email address and phone number."
    if not is_yes(message):
        found = read_contacts(context, PatientUpdate, UPDATE, {"message": message}, "Read corrected contact details")
        flow.contact_update.update({k: v for k, v in found.values.items() if k in {"email", "phone"}})
        for field in found.errors:
            flow.contact_update.pop(field, None)
        if flow.contact_errors:
            flow.step = RECOVERY
            return error_reply(flow.contact_errors)
        flow.editing = None
        return confirm_contacts(flow.contact_update)

    expected = flow.contact_fingerprint
    if expected is None:
        return "Please start a new chat and provide your contact details again."

    # Keep atomic updates, normalization, duplicate-email checks and conflict checks.
    result = replace_contacts(flow.recovery_patient_id, **flow.contact_update, expected=expected)
    if not result["ok"]:
        return result["error"]
    flow.patient = result["patient"]
    flow.verified, flow.returning = True, True
    flow.contact_update = {}
    flow.challenge, flow.contact_fingerprint = None, None
    flow.step = REGISTRY
    return "Your email address and phone number have been updated. " + replies.on_file(flow.patient)


def menu(context: Context, message: str = "") -> str:
    text = message.casefold().strip(" .!")
    if text in {"continue", "continue booking", "resume", "resume booking"} and context.flow.account_return_step:
        flow = context.flow
        flow.step, flow.account_return_step = flow.account_return_step, None
        return flow.account_return_reply
    if text in {"1", "my bookings", "view bookings", "show bookings", "all bookings", "booking history", "show my bookings", "view all bookings"}:
        return history(context)
    if text in {"2", "new appointment", "book appointment", "book an appointment", "book a new appointment", "yes"}:
        return new_appointment(context)
    if text in {"3", "all clinics", "show clinics", "list clinics", "view clinics"}:
        return directory(context)
    return replies.account_menu(context.flow.first_name)


def new_appointment(context: Context) -> str:
    if not context.flow.verified:
        return "Please provide and confirm your contact details first."
    from .complaint import on_entry
    flow = context.flow
    flow.preference, flow.chosen, flow.options = None, None, []
    flow.booking_history = None
    flow.account_return_step, flow.account_return_reply = None, ""
    flow.contact_update, flow.pending = {}, None
    flow.contact_errors, flow.editing = {}, None
    flow.step = COMPLAINT
    return on_entry(context)


def enter_menu(context: Context) -> None:
    flow = context.flow
    if flow.step != MENU:
        flow.account_return_step, flow.account_return_reply = flow.step, flow.last_reply
        flow.step = MENU


def show_menu(context: Context) -> str:
    enter_menu(context)
    return replies.account_menu(context.flow.first_name)


def history(context: Context) -> str:
    flow = context.flow
    if not flow.verified:
        return "Please provide and confirm your contact details before viewing bookings."
    enter_menu(context)
    flow.booking_history = patient_bookings(flow.patient_id, verified=flow.verified)
    return replies.booking_history(flow.booking_history) + "\n" + replies.account_menu(flow.first_name)


def directory(context: Context) -> str:
    if context.flow.verified:
        enter_menu(context)
        suffix = replies.account_menu(context.flow.first_name)
    else:
        suffix = "Provide and confirm your contact details to view personal bookings. You can also say 'end chat'."
    return replies.clinic_directory(all_clinics()) + "\n" + suffix