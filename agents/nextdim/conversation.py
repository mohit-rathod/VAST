"""The state of one conversation, and what a step is handed to do its work.

`Flow` is the memory: where the patient is in the machine and everything learned
so far. `Context` is what one step handler gets: the flow, the model client and
the trace. Keeping them apart is what lets a step be a plain function of two
arguments, so a step can be read, and reasoned about, on its own.

    flow = Flow()
    context = Context(flow, client, on_event)
    reply = steps.HANDLERS[flow.step](context, "yes")
"""

from pydantic import BaseModel

from app.trace import emit
from domain.models import Availability, Complaint, Location, PatientIntake, SlotOption

from .llm import ask

# The steps of the machine, in the order a patient meets them. Each name is what
# the UI trace shows, and each one is a key in steps.HANDLERS.
DETAILS = "details"
REGISTRY = "registry"
COMPLAINT = "complaint"
CLINIC = "clinic"
SLOTS = "slots"
BOOK = "book"
DONE = "done"
VERIFY = "verify"
RECOVERY = "recovery"
RECOVERY_ID = "recovery_identity"
CONTACT_CONFIRM = "contact_confirm"
MENU = "menu"
END_CONFIRM = "end_confirm"

STEP_LABELS = {
    DETAILS: "Collect the patient details",
    REGISTRY: "Check the patient is registered",
    COMPLAINT: "Understand the problem",
    CLINIC: "Name the clinic and ask for a time",
    SLOTS: "Offer clinics and slots",
    BOOK: "Confirm and book",
    DONE: "Finished",
    VERIFY: "Verify ownership of the registered email",
    RECOVERY: "Collect both updated contact details",
    RECOVERY_ID: "Locate the account for recovery",
    CONTACT_CONFIRM: "Confirm the contact update",
    MENU: "Choose an account action",
    END_CONFIRM: "Confirm ending the chat",
}

# How many times the agent may ask a patient to explain their problem again
# before it goes with what it has. The loop is meant to keep going until the
# patient is satisfied, and a patient who never is should still reach a doctor
# rather than a model call that never ends.
MAX_CLARIFICATIONS = 3


class Flow:
    """Everything one conversation knows, and where it is in the machine."""

    def __init__(self) -> None:
        self.step: str = DETAILS
        self.intake = PatientIntake()
        self.patient: dict | None = None
        self.complaint: Complaint | None = None
        self.clarifications: int = 0
        # An address that has been read back and is waiting to be agreed to, so a
        # "yes" after it can only ever mean "that address is right".
        self.pending: Location | None = None
        self.preference: Availability | None = None
        self.options: list[SlotOption] = []
        self.chosen: SlotOption | None = None
        self.booking: dict | None = None
        self.duration_minutes = 30
        self.returning = False
        self.verified = False
        self.recovery_patient_id: int | None = None
        self.contact_update: dict = {}
        self.contact_errors: dict[str, str] = {}
        self.editing: str | None = None
        # Snapshot for conflict-safe contact updates without an email challenge.
        self.contact_fingerprint: tuple[str, str | None] | None = None
        self.challenge = None
        self.verification_purpose = "login"
        self.previous_step: str | None = None
        self.last_reply = ""
        self.resume_reply = ""
        self.account_return_step: str | None = None
        self.account_return_reply = ""
        self.end_reason: str | None = None
        self.booking_history: list[dict] | None = None

    @property
    def patient_id(self) -> int | None:
        """Id of the patient on file, or None before they are registered."""
        return self.patient["id"] if self.patient else None

    @property
    def first_name(self) -> str:
        """How to greet the patient, from the record if there is one."""
        if self.patient:
            return self.patient["first_name"]
        return self.intake.first_name or "there"

    @property
    def speciality(self) -> str | None:
        """The speciality that treats the problem, once the patient has agreed it."""
        return self.complaint.speciality if self.complaint else None

    @property
    def finished(self) -> bool:
        """Is this conversation over?"""
        return self.step == DONE


class Context:
    """What one step handler is given: the flow, the model and the trace.

    `client` is anything with `chat.completions.create`, so a test can pass a
    stub, and `on_event` is any callable taking one event dict, which is how the
    web UI shows each step. See app/trace.py for the event shape.
    """

    def __init__(self, flow: Flow, client=None, on_event=None, verification=None) -> None:
        self.flow = flow
        self.client = client
        self.on_event = on_event
        if verification is None:
            from app.email_delivery import verification_service
            verification = verification_service()
        self.verification = verification

    def emit(self, kind: str, title: str, **data) -> None:
        """Report one thing that just happened, if anyone is listening."""
        emit(self.on_event, kind, title, **data)

    def ask(self, model: type[BaseModel], system: str, payload: dict, label: str) -> BaseModel:
        """One model call, retried once if the reply does not fit `model`."""
        return ask(model, system, payload, self.client, self.on_event, label)