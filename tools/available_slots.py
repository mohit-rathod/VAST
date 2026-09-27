"""Tool: free appointment slots of a clinic."""

from datetime import date, datetime, time, timedelta

from app.db import connect

OPEN_TIME = time(9, 0)
CLOSE_TIME = time(17, 0)
SLOT_MINUTES = 30
FIRST_DAY = date(2026, 9, 30)
DAYS = 5
BUSY_STATUSES = ("booked", "confirmed")


def window() -> list[date]:
    """The days that can be booked."""
    return [FIRST_DAY + timedelta(days=n) for n in range(DAYS)]


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


def available_slots(clinic_id: int, day: date | str | None = None) -> list[dict]:
    """Free slots of one clinic, for a single day or for the whole window."""
    days = [as_date(day)] if day else window()
    marks = ", ".join("?" * len(BUSY_STATUSES))
    free = []
    with connect() as conn:
        for day in days:
            taken = {
                row[0]
                for row in conn.execute(
                    f"SELECT start_time FROM bookings"
                    f" WHERE clinic_id = ? AND slot_date = ? AND status IN ({marks})",
                    (clinic_id, day.isoformat(), *BUSY_STATUSES),
                )
            }
            for start_time, end_time in slots_of_day(day):
                if start_time not in taken:
                    free.append(
                        {
                            "clinic_id": clinic_id,
                            "date": day.isoformat(),
                            "start_time": start_time,
                            "end_time": end_time,
                        }
                    )
    return free
