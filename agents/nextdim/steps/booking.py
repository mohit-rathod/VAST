"""Step: the agreed slot, written down.

Nothing is held while the patient is deciding, so the slot can be taken by
somebody else between being offered and being booked. When that happens the
booking fails and the conversation goes back to the loop of offering slots rather
than telling a patient they are booked when they are not.

A reply that is not a yes is read by the same code that reads a reply to the list
it came from, so a patient who changes their mind, names another clinic or asks
for another time at this point is answered instead of being asked to reply with a
number again.
"""

from app.trace import NOTE, TOOL
from tools.book import book_appointment

from .. import replies
from ..answers import is_yes
from ..conversation import Context, DONE, SLOTS
from .scheduling import choose, offer


def on_entry(context: Context) -> str:
    """The agreed slot, said back before it is written to the database."""
    return replies.read_back(context.flow.chosen)


def book(context: Context, message: str) -> str:
    """Book the agreed slot, once the patient has said yes to it."""
    flow = context.flow
    if flow.chosen is None:
        from .scheduling import ask_when
        return ask_when(context, message)
    if not is_yes(message):
        from ..booking_intent import classify, changes_selected_time
        from ..answers import picked_number
        from .scheduling import ask_when
        if changes_selected_time(message, flow.chosen):
            return ask_when(context, message)
        index = picked_number(message, len(flow.options))
        if index is not None:
            return choose(context, str(index + 1))
        decision = classify(context, message)
        if decision.intent == "change":
            if decision.option_number is not None:
                return choose(context, str(decision.option_number))
            return ask_when(context, message)
        if decision.intent == "decline":
            flow.chosen, flow.step = None, SLOTS
            return "Nothing has been booked. " + replies.slot_choices(flow.options, "Choose another appointment:")
        if decision.intent != "confirm":
            # Preserve the exact selection. Never treat an unclear reply as a
            # date search, a new selection, or permission to write.
            return "Nothing has been booked yet. Use Confirm booking or tell me what to change. " + replies.read_back(flow.chosen)

    context.emit(
        TOOL,
        "Book the slot",
        clinic_id=flow.chosen.clinic_id,
        patient_id=flow.patient_id,
        slot_date=flow.chosen.date,
        start_time=f"{flow.chosen.start_time:%H:%M}",
    )
    result = book_appointment(
        flow.chosen.clinic_id,
        flow.patient_id,
        flow.chosen.date,
        f"{flow.chosen.start_time:%H:%M}",
        duration_minutes=flow.duration_minutes,
    )
    if not result["ok"]:
        context.emit(NOTE, "The appointment could not be booked", error=result["error"])
        explanation = replies.slot_taken() if result.get("taken") else "That appointment can no longer be booked. I have not created a booking. "
        return explanation + reoffer(context)
    flow.booking = result
    flow.step = DONE
    flow.end_reason = "booked"
    flow.challenge = None
    context.emit(TOOL, "Booked", **{key: result[key] for key in ("booking_id", "status")})
    return replies.booked(flow.patient, flow.chosen, flow.booking)


def reoffer(context: Context) -> str:
    """Rank the slots again, now that the one that was agreed is gone."""
    context.flow.options = []
    if context.flow.preference is None:
        return on_entry(context)
    return offer(context)