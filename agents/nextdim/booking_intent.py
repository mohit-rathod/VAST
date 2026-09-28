"""Read booking consent in context, without allowing the model to write anything."""
import re
from zoneinfo import ZoneInfo
from app.trace import NOTE
from domain.chat_models import BookingDecision
from services.date_resolver import DateResolver, resolve_time
from services.duration import appointment_duration
from tools import available_slots as calendar
from .prompts import BOOKING_INTENT


RESOLVER = DateResolver()
NEGATED_BOOKING = re.compile(r"\b(?:do not|don't|dont|not|never)\s+(?:book|confirm|reserve)\b", re.I)


def changes_selected_time(message, selected) -> bool:
    """An explicit conflicting date/time cannot consent to the old selection."""
    duration = appointment_duration(message, scheduling=True)
    selected_minutes = (selected.end_time.hour * 60 + selected.end_time.minute
                        - selected.start_time.hour * 60 - selected.start_time.minute)
    temporal_text = duration.remaining if duration.minutes == selected_minutes else message
    resolved = RESOLVER.resolve(temporal_text, calendar.now(ZoneInfo(selected.zone) if selected.zone else calendar.PORTAL_ZONE))
    clock = resolve_time(temporal_text)
    if resolved.error or clock.error:
        return True
    if resolved.recognized and not resolved.start <= selected.date <= (resolved.end or resolved.start):
        return True
    if clock.at and clock.at != selected.start_time.strftime("%H:%M"):
        return True
    if clock.period != "any":
        low, high = calendar.PERIOD_HOURS[clock.period]
        if not low <= selected.start_time.hour < high:
            return True
    return False


def classify(context, message: str) -> BookingDecision:
    """Unknown or failed model output always leaves the booking uncommitted."""
    if NEGATED_BOOKING.search(message) or message.casefold().strip(" .!") in {
        "no", "no thanks", "not yet", "wait", "hold on", "maybe",
    }:
        return BookingDecision(intent="decline")
    flow = context.flow
    selected = flow.chosen
    try:
        result = context.ask(
            BookingDecision,
            BOOKING_INTENT,
            {
                "message": message,
                "selected_slot": selected.model_dump(mode="json"),
                "displayed_options": [
                    {"number": number, **option.model_dump(mode="json")}
                    for number, option in enumerate(flow.options, 1)
                ],
                "booking_created": False,
            },
            "Interpret confirmation of the selected appointment",
        )
    except Exception as error:
        # This boundary covers SDK transport/refusal failures as well as bad JSON.
        # Do not log exception bodies: upstream errors may contain request data.
        context.emit(NOTE, "Booking intent unavailable; confirmation required", error_type=type(error).__name__)
        return BookingDecision(intent="unclear")
    if result.option_number is not None and result.option_number > len(flow.options):
        return BookingDecision(intent="unclear")
    return result