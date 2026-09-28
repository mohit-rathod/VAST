"""Tool: the best free slots for a patient, ranked by distance and availability.

The patient has agreed on a day and a rough time of day; this finds the clinics
that treat their problem, takes the slot that sits closest to the time they
asked for out of each one, and orders the result. No model is involved, so a
patient can ask for a different time as often as they like without costing a
model call, and two candidates asking at the same moment always get the same
answer for the same state of the database.

The order is lexicographic, which makes it explainable: whatever the patient
pinned down comes first, then distance, then how far the slot is from the time
they asked for, then how much room the clinic has left. See `sort_key`.
"""

from app.trace import NOTE, TOOL, emit

from .available_slots import as_date, available_slots, in_period, minutes_of, window
from .match_clinics import nearest_clinics

OPTIONS = 3

# The time of day each period is really asking for, used to rank the slots
# inside a clinic. Clinics close at 17:00, so "evening" is unbookable and lands
# in the widening below rather than dead-ending.
IDEAL = {"morning": "10:00", "afternoon": "14:00", "evening": "18:00", "any": "12:00"}


def rank_slots(
    patient_id: int,
    day: str | None = None,
    speciality: str | None = None,
    period: str = "any",
    at: str | None = None,
    limit: int = OPTIONS,
    on_event=None,
    *, dates=None, duration_minutes: int = 30, widen: bool = True,
) -> list[dict]:
    """The `limit` best bookable slots for a patient, best first.

    `day` is the day the patient asked for; pass None to search the whole booking
    window. `speciality` keeps only clinics that treat that kind of problem, and
    `at` is a time of day they insisted on. If the day they asked for has nothing
    free in the period they asked for, the window is searched instead and the
    rows come back with `widened` set, so the caller can say why the day changed.
    """
    wanted = as_date(day) if day else None
    clinics = nearest_clinics(patient_id, count=None, speciality=speciality)
    if not clinics:
        # A speciality outside the clinic list would otherwise leave nothing to
        # offer, so every clinic is better than an empty answer.
        emit(on_event, NOTE, f"No clinic treats {speciality}, looking at all of them")
        clinics = nearest_clinics(patient_id, count=None)

    rows = [row for clinic in clinics for row in _slots_of(clinic, wanted, period, at=at, dates=dates, duration_minutes=duration_minutes)]
    widened = False
    if not rows and wanted is not None and widen and dates is None:
        # Nothing free on the day they asked for, in the period they asked for.
        # Look across the whole window rather than sending them back to re-ask for
        # a day that is just as full, and let the caller say why the day moved.
        # The other days are still measured from the day they asked for, so the
        # nearest one comes first.
        emit(
            on_event,
            TOOL,
            f"Nothing free for {speciality or 'any'} on {wanted} in the {period},"
            " widening to the window",
            day=str(wanted),
            period=period,
        )
        rows = [row for clinic in clinics for row in _slots_of(clinic, None, period, wanted, at=at, duration_minutes=duration_minutes)]
        widened = True

    rows.sort(key=lambda row: sort_key(row, time_first=at is not None))
    # Keep only what will be shown, so the number a patient replies with always
    # lines up with the list they were given.
    chosen = rows[:limit]
    emit(
        on_event,
        TOOL,
        f"Ranked {len(rows)} free {speciality or ''} slots by distance and availability",
        wanted=str(wanted) if wanted else "any day",
        period=period,
        at=at or "no fixed time",
        widened=widened,
        options=[
            f'{row["name"]} {row["date"]} {row["start_time"]}, {row["distance_km"]} km,'
            f' {row["free_slots"]} free that day'
            for row in chosen
        ],
    )
    for row in chosen:
        row["widened"] = widened
    return chosen


def sort_key(row: dict, time_first: bool = False) -> tuple:
    """What orders two candidate slots, smallest first.

    Distance is the patient's main concern, so it leads, unless they pinned down
    a time of day, in which case meeting that time leads instead. `day_gap` is 0
    for every row unless the search was widened, where it keeps the nearest day
    first. More free slots left at the clinic breaks the remaining ties, because
    a clinic with room is likelier to still have the slot when they come back.
    """
    near_time, close_by = row["drift_minutes"], row["distance_km"]
    return (
        row["day_gap"],
        near_time if time_first else close_by,
        close_by if time_first else near_time,
        -row["free_slots"],
    )


def _slots_of(
    clinic: dict, wanted, period: str, measure_from=None, *, at=None, dates=None, duration_minutes=30
) -> list[dict]:
    """One candidate row per day for a clinic: its best slot in that period.

    `wanted` is the day to look at, or None for the whole window. `measure_from`
    is the day the patient asked for, which `day_gap` is counted from, so a
    widened search still brings the nearest day first.
    """
    rows = []
    for other in dates if dates is not None else ([wanted] if wanted else window()):
        free = [
            slot
            for slot in available_slots(clinic["clinic_id"], other, duration_minutes=duration_minutes)
            if in_period(slot["start_time"], period)
        ]
        if not free:
            continue
        row = _row(clinic, min(free, key=_drift(period, at)), len(free), period, at)
        row["day_gap"] = abs((other - measure_from).days) if measure_from else 0
        rows.append(row)
    return rows


def _drift(period: str, at: str | None = None):
    """Order slots of a day by how far they are from the time that period means."""
    ideal = minutes_of(at or IDEAL[period])
    return lambda slot: (abs(minutes_of(slot["start_time"]) - ideal), slot["start_time"])


def _row(clinic: dict, slot: dict, free_slots: int, period: str, at: str | None = None) -> dict:
    """A clinic, one of its slots and how that slot was chosen, in one dict."""
    ideal = minutes_of(at or IDEAL[period])
    return {
        "clinic_id": clinic["clinic_id"],
        "name": clinic["name"],
        "speciality": clinic["speciality"],
        "address": clinic["address"],
        "distance_km": clinic["distance_km"],
        "zone": clinic.get("zone", ""),
        "date": slot["date"],
        "start_time": slot["start_time"],
        "end_time": slot["end_time"],
        "free_slots": free_slots,
        "drift_minutes": abs(minutes_of(slot["start_time"]) - ideal),
        "day_gap": 0,
        "widened": False,
    }