"""Step: the details a patient is identified by.

Name, email and phone are the three the portal asks for, and the model is what
turns a sentence of free text into them. Nothing is guessed: a field the message
does not carry stays empty and is asked for again, so the only thing that moves
this step forward is the patient having said all three.
"""

from domain.models import PatientIntake

from .. import replies
from ..contacts import read_contacts
from services.contact_input import error_reply
from ..conversation import Context, REGISTRY
from ..prompts import INTAKE
from .registry import open_registry


def handle(context: Context, message: str) -> str:
    """Take the details out of the message, then ask for whatever is still missing."""
    flow = context.flow
    found = read_contacts(
        context, PatientIntake,
        INTAKE,
        {"message": message, "already_known": flow.intake.model_dump(mode="json")},
        "Ask the model for the name, email and phone",
    )
    for field, value in found.values.items():
        if value is not None:
            setattr(flow.intake, field, value)

    for field in found.errors:
        setattr(flow.intake, field, None)
    if flow.contact_errors:
        return error_reply(flow.contact_errors)

    if flow.intake.missing():
        return replies.need_details(flow.intake.missing())

    flow.step = REGISTRY
    return open_registry(context)


def on_entry(context: Context) -> str:
    """The first thing a patient hears once all three details are in."""
    return replies.ask_details()