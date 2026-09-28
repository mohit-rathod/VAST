"""Deterministic clinic-distance ranking; no SQL and no model calls."""

import math
from collections.abc import Callable
from typing import Any

from domain.ports import ClinicRepository


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance, using the original calculation and rounding rules."""
    lat1, lon1, lat2, lon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    half = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(
        (lon2 - lon1) / 2
    ) ** 2
    return 6371 * 2 * math.asin(math.sqrt(half))


class ClinicService:
    def __init__(
        self, repository: ClinicRepository,
        available_slots: Callable[[int, Any], list[dict]],
        zone_name: Callable[[str | None], str],
        distance: Callable[[float, float, float, float], float] = distance_km,
    ) -> None:
        self.repository = repository
        self.available_slots = available_slots
        self.zone_name = zone_name
        self.distance = distance

    def nearest(
        self, patient_id: int, count: int | None, speciality: str | None = None
    ) -> list[dict]:
        patient, clinics = self.repository.candidates(patient_id, speciality)

        def distance(clinic: dict) -> float:
            return self.distance(
                patient["latitude"], patient["longitude"],
                clinic["latitude"], clinic["longitude"],
            )

        ranked = sorted(clinics, key=distance)
        return [
            {
                "clinic_id": clinic["id"],
                "name": clinic["name"],
                "speciality": clinic["speciality"],
                "address": f'{clinic["address"]}, {clinic["city"]}, {clinic["state"]} {clinic["zip"]}',
                "distance_km": round(distance(clinic), 1),
                "zone": self.zone_name(clinic["zip"]),
            }
            for clinic in (ranked if count is None else ranked[:count])
        ]

    def candidates(self, patient_id: int, day, count: int) -> tuple[dict, list[dict]]:
        patient = self.repository.patient(patient_id)
        candidates = []
        for clinic in self.nearest(patient_id, count):
            free = self.available_slots(clinic["clinic_id"], day)
            candidates.append({
                **clinic,
                "free_slots": [f'{slot["start_time"]}-{slot["end_time"]}' for slot in free],
            })
        return dict(patient), candidates
