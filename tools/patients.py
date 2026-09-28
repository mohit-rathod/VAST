"""Tool: find, register and update a patient record.

The only module that writes to the patients table, so the rules about who may be
matched with whom live in one place. A patient is identified by email and phone
together: the email alone is unique, but two people can share a phone, and
matching on the pair is what stops one patient's details being shown to another.

Writes return the same shape as tools.book: `{"ok": True, "patient": {...}}` or
`{"ok": False, "error": "..."}`. A failure a patient can do something about is a
value here, not an exception.
"""

import sqlite3

from app.db import connect
from app.geo import coordinates_of
from domain.models import Location, PatientIntake, PatientUpdate
from repositories.patients import COLUMNS, SQLitePatientRepository, patient_session
from services.patients import ADDRESS_COLUMNS, UNPLACEABLE, PatientService
from services.patients import reason_for as _reason_for


def _service() -> PatientService:
    return PatientService(lambda: patient_session(connect), coordinates_of)


def find_patient(email: str, phone: str) -> dict | None:
    """The patient registered with this email and phone number together."""
    return _service().find(email, phone)


def register_patient(intake: PatientIntake, place: Location) -> dict:
    """Register a patient, retaining the existing result and error contract."""
    return _service().register(intake, place)


def update_patient(patient_id: int, changes: PatientUpdate | dict) -> dict:
    """Apply only supplied changes and return the refreshed record."""
    return _service().update(patient_id, changes)


def read(patient_id: int) -> dict:
    """Read the current record, or an empty dict if it does not exist."""
    return _service().read(patient_id)


def _address(place: Location | None, **changes) -> dict:
    """Compatibility wrapper for the original address helper."""
    return _service().address(place, **changes)


def _on_file(conn, patient_id: int) -> Location | None:
    """Compatibility wrapper using the caller's existing connection."""
    row = SQLitePatientRepository(conn).location(patient_id)
    return Location(**row) if row else None


def reason_for(error: sqlite3.IntegrityError) -> str:
    """Keep the original helper signature and patient-facing error wording."""
    return _reason_for(error)


def identify_patient(email: str, phone: str):
    from services.identity import IdentityService
    return IdentityService(lambda: patient_session(connect)).identify(email, phone)


def recovery_candidate(email: str) -> int | None:
    from services.identity import IdentityService
    return IdentityService(lambda: patient_session(connect)).recovery_candidate(email)


def replace_contacts(patient_id: int, email: str, phone: str, expected: tuple[str, str | None]) -> dict:
    """Commit the two contacts against the verified record's original fingerprint."""
    return _service().replace_contacts(patient_id, email, phone, expected)