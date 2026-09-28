"""Validate a slot and report the result of an atomic reservation."""

from datetime import date, time, datetime, timedelta

from domain.errors import SlotTaken, StorageConflict
from domain.ports import BookingRepository, SlotGrid


class BookingService:
    def __init__(self, repository: BookingRepository, slot_grid: SlotGrid) -> None:
        self.repository = repository
        self.slot_grid = slot_grid

    def book(
        self, clinic_id: int, patient_id: int, day: date, start_time: str,
        status: str, busy_statuses: tuple[str, ...], duration_minutes: int = 30,
    ) -> dict:
        if duration_minutes not in (30, 60):
            return {"ok": False, "error": "Appointments must be 30 minutes or 1 hour; we cannot book for more than one hour."}
        if status not in ("booked", "confirmed", "cancelled", "completed"):
            return {"ok": False, "error": "Invalid booking status"}
        times = dict(self.slot_grid(day))
        if start_time not in times:
            return {"ok": False, "error": f"{start_time} is not a slot on {day}"}
        end_time = times[start_time]
        if duration_minutes == 60:
            if end_time not in times:
                return {"ok": False, "error": "A full 1-hour appointment does not fit before closing."}
            end_time = times[end_time]
        if (datetime.combine(day, time.fromisoformat(end_time)) - datetime.combine(day, time.fromisoformat(start_time))).total_seconds() != duration_minutes * 60:
            return {"ok": False, "error": "The slot grid cannot provide that duration."}
        try:
            booking_id = self.repository.reserve(
                clinic_id, patient_id, day, start_time, end_time, status, busy_statuses
            )
        except SlotTaken:
            return {
                "ok": False,
                "error": f"clinic {clinic_id} is already booked on {day} at {start_time}",
                "taken": True,
            }
        except StorageConflict as error:
            return {"ok": False, "error": str(error), "taken": True}
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