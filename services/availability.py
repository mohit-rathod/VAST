"""Subtract occupied times from an injected slot grid."""

from datetime import date, datetime, timedelta

from domain.ports import AvailabilityRepository, SlotGrid


class AvailabilityService:
    def __init__(self, repository: AvailabilityRepository, slot_grid: SlotGrid) -> None:
        self.repository = repository
        self.slot_grid = slot_grid

    def available(
        self, clinic_id: int, days: list[date], busy_statuses: tuple[str, ...]
    ) -> list[dict]:
        taken = self.repository.taken_times(clinic_id, days, busy_statuses)
        return [
            {
                "clinic_id": clinic_id,
                "date": day.isoformat(),
                "start_time": start,
                "end_time": end,
            }
            for day in days
            for start, end in self.slot_grid(day)
            if not any(start <= occupied < end for occupied in taken[day.isoformat()])
        ]