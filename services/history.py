"""Booking-history reads with explicit authorization and clinic-local display data."""
from datetime import date
from collections.abc import Callable
from domain.ports import HistoryRepository


class HistoryService:
    def __init__(self, repository: HistoryRepository, zone_name: Callable[[str], str]) -> None:
        self.repository, self.zone_name = repository, zone_name

    def bookings(self, patient_id: int, *, verified: bool) -> list[dict]:
        if not verified or patient_id is None:
            raise PermissionError("Verify the account before reading booking history")
        return [{**r, "weekday": date.fromisoformat(r["slot_date"]).strftime("%A"),
                 "zone": self.zone_name(r["zip"])} for r in self.repository.for_patient(patient_id)]

    def clinics(self) -> list[dict]:
        return [{**r, "zone": self.zone_name(r["zip"])} for r in self.repository.clinics()]