"""Tool: free appointment slots of a clinic.

The slot grid is generated here rather than stored, so a day is always the same
16 half-hour slots between opening and closing, and the periods a patient can ask
for are defined against that same grid.

Every day and every time here belongs to a zone, not to UTC. A patient who says
"Friday morning" means Friday morning where they live, and the clinic that is
offered the slot works in its own local time, so the two zones are carried
alongside the dates rather than assumed.
"""

import os
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app import config  # Load .env for direct tool/CLI use.
from app.db import connect
from app.geo import DEFAULT_ZONE, zone_of
from repositories.bookings import SQLiteAvailabilityRepository
from services.availability import AvailabilityService

OPEN_TIME = time(9, 0)
CLOSE_TIME = time(17, 0)
SLOT_MINUTES = 30
FIRST_DAY = date.fromisoformat(os.environ["VAST_FIRST_DAY"]) if os.getenv("VAST_FIRST_DAY") else None
DAYS = int(os.getenv("VAST_BOOKING_DAYS", "14"))
if not 1 <= DAYS <= 366:
    raise ValueError("VAST_BOOKING_DAYS must be between 1 and 366")
BUSY_STATUSES = ("booked", "confirmed")

# The zone used before a patient's address is known, and the fallback for a ZIP
# the geocoder does not have. Every booking day is counted from here.
PORTAL_ZONE = ZoneInfo(DEFAULT_ZONE)

# The hours a slot has to start in to count as the period the patient asked for.
# "any" is not a time of day, it is the absence of a preference, which is why it
# spans the whole day.
PERIOD_HOURS = {
    "morning": (0, 12),
    "afternoon": (12, 17),
    "evening": (17, 24),
    "any": (0, 24),
}


def window(zone: ZoneInfo | None = None) -> list[date]:
    """The days that can be booked."""
    start = FIRST_DAY or now(zone).date()
    return [start + timedelta(days=n) for n in range(DAYS)]


def zone_for(zip_code: str | None) -> ZoneInfo:
    """The zone a patient's or a clinic's times are read in."""
    return zone_of(zip_code) if zip_code else PORTAL_ZONE


def now(zone: ZoneInfo | None = None) -> datetime:
    """This moment in the given zone, so a day that has passed can be recognised."""
    return datetime.now(zone or PORTAL_ZONE)


def moment(day: date | str, start_time: str, zone: ZoneInfo | None = None) -> datetime:
    """One slot as a real instant in a real zone, rather than a bare HH:MM.

    This is what a day, a period and a clock time become once they have to be
    compared with now, or read out to a patient who is somewhere else.
    """
    return datetime.combine(
        as_date(day), time.fromisoformat(start_time), tzinfo=zone or PORTAL_ZONE
    )


def bookable_days(zone: ZoneInfo | None = None) -> list[dict]:
    """The open days as the model needs them to resolve a day of the week.

    A patient says "Monday" or "this Friday", never an ISO date. Each entry
    carries the weekday name and how far off the day is, so the model can match
    what the patient said against the open days instead of guessing which
    calendar date "Monday" means this week. `in_days` is 0 for today and 1 for
    tomorrow, which is what "this weekend" or "first thing" has to be read
    against. `bookable` is false for a day that has already gone, so a request
    for it is refused rather than moved.
    """
    today = now(zone).date()
    return [
        {
            "date": day.isoformat(),
            "weekday": day.strftime("%A"),
            "in_days": (day - today).days,
            "bookable": day >= today,
        }
        for day in window(zone)
    ]


def slots_of_day(day: date) -> list[tuple[str, str]]:
    """Every slot of one day as (start_time, end_time)."""
    start = datetime.combine(day, OPEN_TIME)
    closing = datetime.combine(day, CLOSE_TIME)
    slots = []
    while start < closing:
        end = start + timedelta(minutes=SLOT_MINUTES)
        slots.append((start.strftime("%H:%M"), end.strftime("%H:%M")))
        start = end
    return slots


def as_date(value: date | str) -> date:
    """Accept a date or a 'YYYY-MM-DD' string."""
    return value if isinstance(value, date) else date.fromisoformat(value)


def minutes_of(clock: str) -> int:
    """'14:30' as minutes after midnight, so times can be compared as numbers."""
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


def in_period(start_time: str, period: str) -> bool:
    """Does a HH:MM slot start inside the period the patient asked for?"""
    low, high = PERIOD_HOURS[period]
    return low <= int(start_time[:2]) < high


def available_slots(clinic_id: int, day: date | str | None = None,
                    duration_minutes: int = SLOT_MINUTES) -> list[dict]:
    """Future free intervals, in clinic-local time and inside the configured window."""
    repository = SQLiteAvailabilityRepository(connect)
    zone = zone_for(repository.clinic_zip(clinic_id))
    allowed = window(zone)
    days = [as_date(day)] if day else allowed
    days = [d for d in days if d in allowed]
    if duration_minutes not in (30, 60):
        raise ValueError("Appointments must be 30 minutes or 1 hour")
    service = AvailabilityService(repository, lambda d: appointment_grid(d, duration_minutes))
    current = now(zone)
    return [s for s in service.available(clinic_id, days, BUSY_STATUSES)
            if moment(s["date"], s["start_time"], zone) > current]


def appointment_grid(day: date, duration_minutes: int = SLOT_MINUTES) -> list[tuple[str, str]]:
    """One-hour choices span two adjacent grid cells, not just the first half."""
    if duration_minutes not in (30, 60):
        raise ValueError("Appointments must be 30 minutes or 1 hour")
    result = []
    for start, _ in slots_of_day(day):
        end = datetime.combine(day, time.fromisoformat(start)) + timedelta(minutes=duration_minutes)
        if end.time() <= CLOSE_TIME and end.date() == day:
            result.append((start, end.strftime("%H:%M")))
    return result