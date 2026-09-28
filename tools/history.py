"""History tool wiring. Patient ID comes from the verified session, not the model."""
from app.db import connect
from app.geo import zone_name_of
from repositories.history import SQLiteHistoryRepository
from services.history import HistoryService


def patient_bookings(patient_id: int, *, verified: bool) -> list[dict]:
    return HistoryService(SQLiteHistoryRepository(connect), zone_name_of).bookings(patient_id, verified=verified)


def all_clinics() -> list[dict]:
    return HistoryService(SQLiteHistoryRepository(connect), zone_name_of).clinics()