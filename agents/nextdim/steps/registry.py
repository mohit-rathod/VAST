"""Step: is this patient registered, and is what we hold about them right?

Email and phone together are the identity, so they decide whether there is a
record to reuse. This step has one loop and it runs until the patient is happy
with it: either a returning patient correcting something, or a new patient giving
an address the portal is able to place. Nothing is written before it has been
read back to them, and every write re-reads the record, so what is quoted back is
what is actually stored. A reply that is not a word the portal knows is put to
the model, so agreeing in their own words moves them on instead of being read as
a correction they never made.
"""

from app.geo import coordinates_of
from app.trace import NOTE, TOOL
from domain.models import LOCATION_FIELDS, Location, PatientUpdate

from tools.patients import find_patient, register_patient, update_patient

from .. import replies
from ..contacts import read_contacts
from services.contact_input import error_reply
from ..answers import is_yes
from ..conversation import COMPLAINT, Context
from ..prompts import UPDATE
from .complaint import is_confirmation
from .complaint import on_entry as ask_problem


def open_registry(context: Context) -> str:
    """Look the patient up and read the record back, or ask for what is missing.

    This is the first thing that happens once the details are in. It runs again
    whenever the patient changes their name, email or phone, because a different
    number may belong to somebody who is already registered.
    """
    flow = context.flow
    from tools.patients import identify_patient
    from ..conversation import RECOVERY, RECOVERY_ID
    from .account import begin_verification
    match = identify_patient(flow.intake.email, flow.intake.phone)
    if match.status == "missing":
        return replies.need_address(flow.intake.first_name or "there")
    if match.status == "ambiguous":
        flow.step = RECOVERY_ID
        return "The details do not identify one account. Please provide the email currently on file to recover it."
    if match.status == "mismatch":
        flow.recovery_patient_id = match.patient_id
        flow.step = RECOVERY
        return replies.contact_mismatch()
    return begin_verification(context, match.patient_id, "login")


def handle(context: Context, message: str) -> str:
    """Settle the record, looping here until the patient is happy with it."""
    flow = context.flow
    if flow.editing == "patient":
        return _changed(context, message)
    if flow.pending is not None:
        # An address has been read back and is waiting to be agreed to. Saying so
        # in their own words agrees to it just as much as a "yes" does.
        return _save(context) if is_confirmation(context, message) else _changed(context, message)
    if is_yes(message):
        if flow.patient is None:
            return replies.need_address(flow.intake.first_name or "there")
        return _continue(context)
    return _changed(context, message)


def _changed(context: Context, message: str) -> str:
    """Read a correction out of the message and act on it.

    Anything the message does not mention is left alone, so a patient who only
    wants to change their phone number does not have to repeat the rest.
    """
    flow = context.flow
    found = read_contacts(
        context, PatientUpdate,
        UPDATE,
        {
            "message": message,
            "registered": flow.patient is not None,
            "on_file": replies.address_of(flow.patient) if flow.patient else None,
        },
        "Ask the model what the patient wants changed",
    )
    if flow.contact_errors:
        return error_reply(flow.contact_errors)
    change = PatientUpdate(**found.values)
    flow.editing = None
    if not change.changes():
        context.emit(NOTE, "Nothing in the message looked like a change", said=message)
        if is_confirmation(context, message):
            # Nothing to change, said the way a patient says it: "that is my
            # address", "nothing else", which means the record is already right.
            return _continue(context)
        return replies.nothing_to_change()
    if change.moves():
        return _read_address(context, change)
    return _save_details(context, change)


def _read_address(context: Context, change: PatientUpdate) -> str:
    """Put the new address to the patient before anything is written to it."""
    flow = context.flow
    place = _place_of(flow, change)
    if place is None:
        return replies.need_the_rest_of_the_address()
    if coordinates_of(place.zip) is None:
        context.emit(TOOL, "No coordinates for that ZIP, asking again", zip=place.zip)
        return replies.unregistered_address()

    flow.pending = place
    return replies.confirm_address(place)


def _save(context: Context) -> str:
    """Write the address the patient has just agreed to, and read the record back."""
    flow = context.flow
    place, flow.pending = flow.pending, None
    created = flow.patient is None
    if created:
        result = register_patient(flow.intake, place)
    else:
        result = update_patient(flow.patient_id, place.model_dump(mode="json"))

    if not result["ok"]:
        context.emit(NOTE, "The record could not be saved", error=result["error"])
        return f"I could not save that: {result['error']}. Could you say it another way?"

    flow.patient = result["patient"]
    flow.verified = True
    context.emit(
        TOOL,
        "Created the patient record" if created else "Saved the address on file",
        patient_id=flow.patient_id,
        **place.model_dump(mode="json"),
    )
    return replies.registered(flow.patient) if created else replies.on_file(flow.patient)


def _save_details(context: Context, change: PatientUpdate) -> str:
    """Change the name, email or number of somebody we hold a record for."""
    flow = context.flow
    if flow.patient is None:
        # Nothing is written yet, so the details to register are simply corrected.
        # The identity may now belong to a patient who is already registered.
        for name, value in change.changes().items():
            if name in flow.intake.model_fields:
                setattr(flow.intake, name, value)
        return open_registry(context)

    result = update_patient(flow.patient_id, change)
    if not result["ok"]:
        context.emit(NOTE, "The correction could not be saved", error=result["error"])
        return f"I could not save that: {result['error']}. Could you say it another way?"

    context.emit(
        TOOL, "Updated the patient record", patient_id=flow.patient_id, **change.changes()
    )
    flow.patient = result["patient"]
    return replies.on_file(flow.patient)


def _place_of(flow, change: PatientUpdate) -> Location | None:
    """The new address, with whatever the message left out taken from the record.

    Only the address fields are carried across, because a message that changes
    where somebody lives often repeats who they are, and a phone number quoted
    back in the same breath is not part of an address.

    None means there is not enough to place a patient, which is asked for again
    rather than guessed at.
    """
    given = change.changes()
    on_file = (
        {name: flow.patient[name] for name in LOCATION_FIELDS} if flow.patient else {}
    )
    if any(not given.get(name, on_file.get(name)) for name in LOCATION_FIELDS):
        return None
    moved = {name: given[name] for name in LOCATION_FIELDS if name in given}
    return Location(**{**on_file, **moved})


def _continue(context: Context) -> str:
    if context.flow.returning:
        from ..conversation import MENU
        context.flow.step = MENU
        return replies.account_menu(context.flow.first_name)
    context.flow.step = COMPLAINT
    return ask_problem(context)