"""Step: what is actually wrong, in the patient's own words and theirs agreed.

The model names the speciality and restates the problem, and the patient has the
last word: a reply that is not a confirmation starts the loop again with a prompt
that asks for more detail, and each round keeps what was already understood so the
restatement gets sharper rather than starting over. Reading the reply is the
model's work, because a patient confirms in their own words and not only in the
ones the portal knows. The loop is left when the patient agrees they have been
understood, or when they have had their chances to say it differently and the best
understanding so far goes to the doctor with them.
"""

from app.trace import NOTE, TOOL
from domain.models import Complaint, Confirmation

from tools.patients import update_patient

from .. import replies
from ..answers import is_yes
from ..conversation import CLINIC, MAX_CLARIFICATIONS, Context
from ..prompts import CLARIFYING, CONFIRMING
from ..prompts import COMPLAINT as COMPLAINT_PROMPT
from .scheduling import on_entry as name_clinic


def on_entry(context: Context) -> str:
    """The first question of this step, before anything has been described."""
    context.flow.complaint = None
    context.flow.clarifications = 0
    return replies.ask_problem(context.flow.first_name)


def handle(context: Context, message: str) -> str:
    """Understand the problem, then keep asking until the patient agrees.

    With nothing understood yet, the message is the description. With a
    restatement already on the table, the message is either the agreement that
    ends the loop or the correction that restarts it.
    """
    flow = context.flow
    if flow.complaint is None:
        flow.complaint = _understood(context, message)
        return replies.understood(flow.complaint)
    if flow.editing == "complaint":
        flow.complaint = _clarified(context, message)
        flow.editing = None
        return replies.understood(flow.complaint)
    if is_confirmation(context, message):
        return _agreed(context, settled=True)
    if flow.clarifications >= MAX_CLARIFICATIONS:
        return _agreed(context, settled=False)
    flow.complaint = _clarified(context, message)
    return replies.understood(flow.complaint)


def is_confirmation(context: Context, message: str) -> bool:
    """Is the patient saying the agent has it right, or adding to it?

    A plain "yes" is already known, but people confirm in their own words, and
    "this is exactly my problem" is a confirmation just as much as "yes" is. The
    model reads the reply, which is what takes the patient out of the loop instead
    of restating the same thing back at them.
    """
    if is_yes(message):
        return True
    return context.ask(
        Confirmation,
        CONFIRMING,
        {"message": message},
        "Ask the model whether the patient confirmed",
    ).agreed


def _clarified(context: Context, message: str) -> Complaint:
    """Take what the patient added on top of what is already understood."""
    flow = context.flow
    flow.clarifications += 1
    return _understood(context, message)


def _understood(context: Context, message: str) -> Complaint:
    """Read the problem out of the message, in the words of the patient.

    A first description is turned into a restatement as it stands. A later one
    arrives with the previous understanding in the payload and the prompt that
    asks for detail, so the model adds to it instead of replacing it.
    """
    flow = context.flow
    previous = flow.complaint
    payload = {"message": message}
    if previous is not None:
        payload["already_understood"] = previous.model_dump(mode="json")
    complaint = context.ask(
        Complaint,
        COMPLAINT_PROMPT + (CLARIFYING if previous is not None else ""),
        payload,
        "Ask the model to name the speciality behind the complaint",
    )
    context.emit(
        TOOL,
        f"Understood the problem as {complaint.speciality}",
        round=flow.clarifications,
        **complaint.model_dump(mode="json"),
    )
    return complaint


def _agreed(context: Context, settled: bool) -> str:
    """The problem is settled, so it is recorded and the clinic is named."""
    flow = context.flow
    flow.step = CLINIC
    _record(context)
    lead = replies.settled() if settled else replies.not_settled()
    return lead + name_clinic(context)


def _record(context: Context) -> None:
    """Put the agreed complaint on the patient's record, for whoever sees them next.

    A record that will not take it is not worth holding the patient up for, so
    the booking carries on and the problem is read out at the appointment.
    """
    flow = context.flow
    result = update_patient(flow.patient_id, {"complaints": flow.complaint.description})
    if result["ok"]:
        flow.patient = result["patient"]
        context.emit(
            TOOL,
            "Recorded the complaint on the patient",
            patient_id=flow.patient_id,
            complaints=flow.complaint.description,
        )
    else:
        context.emit(NOTE, "The complaint could not be recorded", error=result["error"])