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
    dates = [want.date + timedelta(days=i) for i in range(((want.end_date or want.date) - want.date).days + 1)]
    rows = rank_slots(flow.patient_id, day=want.date, speciality=flow.speciality,
                      period=want.period, at=want.at, dates=dates, widen=False,
                      duration_minutes=flow.duration_minutes, on_event=context.on_event)
    flow.options, flow.chosen = [SlotOption.from_row(row) for row in rows], None
    if not rows:
        flow.step = CLINIC
        return (f"No available {flow.duration_minutes}-minute appointments match {_range(want)} "
                f"{('in the ' + want.period) if want.period != 'any' else ''} {replies.clock(_zone(flow))}. "
                "I have not changed your requested dates or made a booking. Please choose another date or time, or say 'end chat'.")
    flow.step = SLOTS
    return replies.slot_choices(flow.options, _header(flow, rows[0]["widened"]))


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
    text = f"For {_range(want)}, "
    text += f"requested start {want.at}, " if want.at else ""
    text += f"{flow.duration_minutes}-minute appointments"
    if want.at:
        text += " (closest available start times are listed explicitly below)"
    return text + ":"