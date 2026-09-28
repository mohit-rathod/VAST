"""Tool: book a clinic appointment.

Two candidates can only ever take one slot, and this is the module that decides
which of them gets it. Four things stand in the way, in order of cost:

    LOCK              serialises the threads of this process,
    BEGIN IMMEDIATE   takes the SQLite write lock before anything is read,
    the re-check      refuses a slot that went while the patient was deciding,
    UNIQUE            rejects the loser of a race nobody could have caught.

The first two mean only one caller is ever looking at a slot, the third turns
the common case into a sentence for the patient instead of an exception, and the
last one is what actually makes a double booking impossible.
"""

import threading

from app.db import connect
from repositories.bookings import SQLiteBookingRepository
from services.booking import BookingService

from .available_slots import BUSY_STATUSES, as_date, slots_of_day, moment, window, zone_for
from . import available_slots as calendar
from repositories.bookings import SQLiteAvailabilityRepository

LOCK = threading.Lock()


def book_appointment(
    clinic_id: int, patient_id: int, slot_date, start_time: str, status: str = "booked",
    duration_minutes: int = 30,
) -> dict:
    """Book one slot of one clinic, or say why it could not be booked."""
    try:
        day = as_date(slot_date)
        zone = zone_for(SQLiteAvailabilityRepository(connect).clinic_zip(clinic_id))
        if day not in window(zone) or moment(day, start_time, zone) <= calendar.now(zone):
            return {"ok": False, "error": "That appointment is in the past or outside the booking window."}
    except (TypeError, ValueError):
        return {"ok": False, "error": "Please provide a valid appointment date and time."}
    repository = SQLiteBookingRepository(connect, LOCK)
    service = BookingService(repository, slots_of_day)
    return service.book(
        clinic_id, patient_id, day, start_time, status, BUSY_STATUSES, duration_minutes
    )


def _is_taken(conn, clinic_id: int, day, start_time: str) -> bool:
    """Compatibility helper; only call while the SQLite write lock is held."""
    return SQLiteBookingRepository.is_taken(conn, clinic_id, day, start_time, BUSY_STATUSES)