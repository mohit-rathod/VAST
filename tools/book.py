"""Tool: book a clinic appointment."""

import sqlite3
import threading

from app.db import connect

from .available_slots import as_date, slots_of_day

LOCK = threading.Lock()


def book_appointment(
    clinic_id: int, patient_id: int, slot_date, start_time: str, status: str = "booked"
) -> dict:
    """Book one slot of one clinic.

    LOCK serialises threads, BEGIN IMMEDIATE takes the SQLite write lock before
    we read, and UNIQUE (clinic_id, slot_date, start_time) rejects the loser of a
    race, so two concurrent callers can never take the same slot.
    """
    day = as_date(slot_date)
    times = dict(slots_of_day(day))
    if start_time not in times:
        return {"ok": False, "error": f"{start_time} is not a slot on {day}"}

    end_time = times[start_time]
    with LOCK:
        conn = connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                f"INSERT INTO bookings"
                f" (clinic_id, patient_id, slot_date, start_time, end_time, status)"
                f" VALUES (?, ?, ?, ?, ?, ?)",
                (clinic_id, patient_id, day.isoformat(), start_time, end_time, status),
            )
            conn.commit()
            booking_id = cursor.lastrowid
        except sqlite3.IntegrityError as error:
            conn.rollback()
            return {"ok": False, "error": str(error)}
        finally:
            conn.close()

    return {
        "ok": True,
        "booking_id": booking_id,
        "clinic_id": clinic_id,
        "patient_id": patient_id,
        "slot_date": day.isoformat(),
        "start_time": start_time,
        "end_time": end_time,
        "status": status,
    }
