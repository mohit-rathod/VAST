"""Conversation-wide account actions and a single explicit end confirmation."""
import re
from . import replies
from .answers import is_yes
from .actions import actions
from .conversation import (END_CONFIRM, DONE, MENU, RECOVERY_ID, CLINIC, SLOTS, BOOK,
                           VERIFY, CONTACT_CONFIRM, RECOVERY, DETAILS, REGISTRY, COMPLAINT)


def is_end_request(message: str) -> bool:
    text = message.casefold().strip(" .!?")
    if re.search(r"\b(don't|do not|not|never)\b", text):
        return False
    if text in {"quit", "exit", "stop", "bye", "goodbye", "i am done", "i'm done", "stop chatting"}:
        return True
    return bool(re.search(r"\b(end|close|stop|cancel|exit|leave|finish)\s+(?:(?:the|this|my)\s+)?(?:chat|conversation|session)\b", text))


def handle(context, message: str) -> str | None:
    flow = context.flow
    text = message.casefold().strip(" .!?")
    if flow.step == END_CONFIRM:
        if is_yes(message) or text in {"end", "end now", "confirm end", "yes end chat"}:
            flow.step, flow.end_reason = DONE, "ended"
            if flow.challenge:
                flow.challenge.consumed = True
            flow.challenge, flow.patient, flow.verified = None, None, False
            flow.contact_update, flow.options, flow.chosen = {}, [], None
            flow.contact_fingerprint = None
            flow.contact_errors, flow.editing = {}, None
            flow.booking_history = None
            return replies.ended()
        if text in {"no", "n", "continue", "no continue", "no, continue", "keep chatting", "do not end", "don't end"}:
            flow.step = flow.previous_step
            return "Continuing the chat. " + flow.resume_reply
        return replies.confirm_end()
    if is_end_request(message):
        flow.previous_step, flow.resume_reply = flow.step, flow.last_reply
        flow.step = END_CONFIRM
        return replies.confirm_end()
    if text in {"recover account", "recover my account", "already registered", "i am already registered"} and not flow.verified:
        flow.step = RECOVERY_ID
        flow.contact_update = {}
        flow.contact_errors, flow.editing = {}, None
        flow.contact_fingerprint = None
        flow.challenge = None
        return "Please provide the email currently on file. I will ask for both updated contact details and your confirmation before saving. No email will be sent."
    if text in {"register new patient", "new patient", "i am new", "i am a new patient"} and not flow.verified:
        if flow.intake.missing():
            flow.step = DETAILS
            return replies.need_details(flow.intake.missing())
        flow.step, flow.challenge, flow.recovery_patient_id = REGISTRY, None, None
        flow.contact_update = {}
        flow.contact_fingerprint = None
        return replies.need_address(flow.intake.first_name or "there")
    if re.search(r"\b(cancel|delete)\s+(?:my\s+)?(?:booking|appointment)\b", text):
        return "This chat cannot cancel an existing appointment. Contact the clinic. To end only this conversation, say 'end chat'."
    # Exact button payloads are deterministic and never need an LLM call.
    if text == "keep current details" and flow.editing and not flow.contact_errors:
        editing, flow.editing = flow.editing, None
        if editing == "complaint":
            return replies.understood(flow.complaint)
        if editing == "contacts":
            from .steps.account import confirm_contacts
            return confirm_contacts(flow.contact_update)
        return replies.confirm_address(flow.pending) if flow.pending else replies.on_file(flow.patient)
    if text in {"edit details", "change address"} and flow.step == REGISTRY and (flow.patient or flow.pending):
        flow.editing = "patient"
        return "Please provide the details you want to correct. Nothing new has been saved."
    if text == "edit contact details" and flow.step == CONTACT_CONFIRM:
        flow.editing = "contacts"
        return "Please provide your corrected email or phone. I will read both back before saving."
    if text == "change problem details" and flow.step == COMPLAINT and flow.complaint:
        flow.editing = "complaint"
        return "Please tell me what to correct or add to the problem description."
    if text in {"change date", "choose another slot"} and flow.step in {BOOK, SLOTS, CLINIC}:
        flow.chosen = None
        if text == "choose another slot" and flow.options:
            flow.step = SLOTS
            return replies.slot_choices(flow.options, "Nothing has been booked. Choose an appointment:")
        flow.step, flow.preference, flow.options = CLINIC, None, []
        return replies.ask_time()
    from .steps import account
    if re.search(r"\b(my bookings|all (?:my )?bookings|booking history|show bookings|view bookings)\b", text):
        return account.history(context)
    if text in {"all clinics", "show clinics", "list clinics", "view clinics"}:
        return account.directory(context)
    if text in {"new appointment", "book appointment", "book an appointment", "book a new appointment"}:
        return account.new_appointment(context)
    if text in {"help", "options", "menu"}:
        if flow.verified:
            return account.show_menu(context)
        return "Provide your name, email and phone to begin, or say 'recover account' if your contact details have changed. You can 'end chat' at any time."
    return None