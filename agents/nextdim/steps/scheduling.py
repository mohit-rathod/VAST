"""Deterministic date/time interpretation, strict ranges, and explicit confirmation."""
from datetime import timedelta
from zoneinfo import ZoneInfo
from app.trace import NOTE, TOOL
from domain.models import Availability, SlotOption, SlotPick
from services.date_resolver import DateResolver, DateResolution, resolve_time
from tools.available_slots import bookable_days, window, zone_for
from tools import available_slots as calendar
from tools.match_clinics import nearest_clinics
from tools.rank_slots import rank_slots
from .. import replies
from ..answers import picked_number
from ..conversation import BOOK, CLINIC, Context, SLOTS
from ..prompts import SLOT

RESOLVER = DateResolver()
NEARBY_DAY_LIMIT = 2


def on_entry(context: Context) -> str:
    flow = context.flow
    zone = _zone(flow)
    clinics = nearest_clinics(flow.patient_id, count=None, speciality=flow.speciality)
    context.emit(TOOL, "Find matching nearby clinics", patient_id=flow.patient_id,
                 timezone=zone.key, clinic_count=len(clinics))
    flow.options, flow.chosen = [], None
    return replies.needs_clinic(flow.speciality, clinics, zone)


def ask_when(context: Context, message: str) -> str:
    return _wanted(context, message) or offer(context)


def offer(context: Context) -> str:
    flow = context.flow
    if flow.preference is None:
        flow.step = CLINIC
        return replies.ask_time(_zone(flow))

    want = flow.preference
    zone = _zone(flow)

    # First search exactly the date/date-range the patient requested.
    dates = [
        want.date + timedelta(days=i)
        for i in range(
            ((want.end_date or want.date) - want.date).days + 1
        )
    ]

    rows = rank_slots(
        flow.patient_id,
        day=want.date,
        speciality=flow.speciality,
        period=want.period,
        at=want.at,
        dates=dates,
        widen=False,
        duration_minutes=flow.duration_minutes,
        on_event=context.on_event,
    )

    widened = False

    # Requested date/range had no matching slots.
    # Search only within +/- 2 days and never offer today/past dates.
    if not rows:
        nearby = _nearby_dates(want, zone)

        if nearby:
            context.emit(
                NOTE,
                "No appointments matched the requested date; checking nearby dates",
                requested_start=str(want.date),
                requested_end=str(want.end_date or want.date),
                nearby_dates=[str(day) for day in nearby],
                max_day_offset=NEARBY_DAY_LIMIT,
            )

            rows = rank_slots(
                flow.patient_id,
                day=want.date,
                speciality=flow.speciality,
                period=want.period,
                at=want.at,
                dates=nearby,
                widen=False,
                duration_minutes=flow.duration_minutes,
                on_event=context.on_event,
            )

            widened = bool(rows)

            for row in rows:
                row["widened"] = widened

    flow.options = [SlotOption.from_row(row) for row in rows]
    flow.chosen = None

    if not rows:
        flow.step = CLINIC

        return (
            f"No available {flow.duration_minutes}-minute appointments match "
            f"{_range(want)} "
            f"{('in the ' + want.period) if want.period != 'any' else ''} "
            f"{replies.clock(zone)}. "
            f"I also checked up to {NEARBY_DAY_LIMIT} days before and after "
            "your request, using only dates after today. "
            "I have not made a booking. "
            "Please choose another date or time, or say 'end chat'."
        )

    flow.step = SLOTS

    return replies.slot_choices(
        flow.options,
        _header(flow, widened or rows[0]["widened"]),
    )


def choose(context: Context, message: str) -> str:
    flow = context.flow
    if not flow.options:
        return ask_when(context, message)
    # Calendar requests must not be mistaken for option numbers.
    resolved = RESOLVER.resolve(message, calendar.now(_zone(flow)))
    clock = resolve_time(message)
    if resolved.recognized or clock.mentioned or clock.error:
        return ask_when(context, message)
    index = picked_number(message, len(flow.options))
    if index is None:
        pick = _picked(context, message)
        if pick.another_time:
            return ask_when(context, message)
        index = pick.number - 1 if pick.number is not None else None
    if index is not None and 0 <= index < len(flow.options):
        flow.chosen, flow.step = flow.options[index], BOOK
        return replies.read_back(flow.chosen)
    return replies.pick_one(flow.options)


def _picked(context: Context, message: str) -> SlotPick:
    pick = context.ask(SlotPick, SLOT,
                       {"message": message, "options": replies.options_of(context.flow.options)},
                       "Read which displayed appointment the patient means")
    if pick.number is not None and pick.number > len(context.flow.options):
        pick.number = None
    return pick


def _wanted(context: Context, message: str) -> str:
    flow, zone = context.flow, _zone(context.flow)
    current = calendar.now(zone)
    flow.step = CLINIC
    flow.options, flow.chosen = [], None
    resolved, clock = RESOLVER.resolve(message, current), resolve_time(message)
    if flow.preference and message.casefold().strip(" .!") in {"any time", "anytime"}:
        resolved = DateResolution()  # Clear only the time filter, not the selected dates.
    if resolved.error or clock.error:
        flow.preference = None
        return resolved.error or clock.error
    if not resolved.recognized:
        if flow.preference is None or not clock.mentioned:
            return replies.ask_time(zone)
        start, end = flow.preference.date, flow.preference.end_date
    else:
        start, end = resolved.start, resolved.end or resolved.start
    available_days = [d for d in window(zone) if d >= current.date() and start <= d <= (end or start)]
    if not available_days:
        flow.preference = None
        description = resolved.description or replies.say_day(start)
        return (f"I understood {description}. That is in the past or outside the current booking window. "
                f"Appointments can be searched from {replies.say_day(window(zone)[0])} through "
                f"{replies.say_day(window(zone)[-1])}, 09:00 to 17:00 {replies.clock(zone)}. "
                "Please choose a date in that window.")
    previous = flow.preference
    # A new day clears an old exact time unless the patient repeats it. A time-only
    # follow-up retains the already-resolved date range.
    want = Availability(date=available_days[0], end_date=available_days[-1],
                        weekday=available_days[0].strftime("%A"),
                        period=clock.period, at=clock.at)
    flow.preference = want
    flow.options, flow.chosen = [], None
    context.emit(TOOL, "Resolved the requested dates and time", date=str(want.date),
                 end_date=str(want.end_date), timezone=zone.key, period=want.period,
                 at=want.at, duration_minutes=flow.duration_minutes)
    return ""


def _bookable(day, days: list[dict]) -> bool:
    return day.isoformat() in {entry["date"] for entry in days if entry["bookable"]}


def _zone(flow) -> ZoneInfo:
    return zone_for(flow.patient["zip"] if flow.patient else None)


def _range(want: Availability) -> str:
    return replies.say_day(want.date) if want.end_date in (None, want.date) else f"{replies.say_day(want.date)} through {replies.say_day(want.end_date)}"


def _header(flow, widened: bool = False) -> str:
    want = flow.preference

    if widened:
        text = (
            f"No available appointment matched {_range(want)}. "
            f"Here are the nearest available choices within "
            f"{NEARBY_DAY_LIMIT} days of your request, "
        )
    else:
        text = f"For {_range(want)}, "

    text += f"requested start {want.at}, " if want.at else ""
    text += f"{flow.duration_minutes}-minute appointments"

    if want.at:
        text += " (closest available start times are listed explicitly below)"

    return text + ":"


def _nearby_dates(want: Availability, zone: ZoneInfo) -> list:
    """Nearby fallback dates, preferring later dates and staying after today.

    The requested date/range is searched first. Only when that search has no
    matching slot do we consider dates up to two days outside the request.

    Search order for each distance:
        +1 day
        -1 day
        +2 days
        -2 days

    Every fallback date must:
        - be inside the configured booking window
        - not be inside the originally requested range
        - be strictly after today's real date
    """

    start = want.date
    end = want.end_date or want.date

    today = calendar.now(zone).date()
    allowed = set(window(zone))

    requested = {
        start + timedelta(days=i)
        for i in range((end - start).days + 1)
    }

    result = []

    for offset in range(1, NEARBY_DAY_LIMIT + 1):
        candidates = (
            end + timedelta(days=offset),
            start - timedelta(days=offset),
        )

        for candidate in candidates:
            if candidate <= today:
                continue

            if candidate not in allowed:
                continue

            if candidate in requested:
                continue

            if candidate in result:
                continue

            result.append(candidate)

    return result
    