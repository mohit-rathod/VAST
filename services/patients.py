"""Patient registration and correction rules, independent of SQLite."""

from domain.errors import StorageConflict
from domain.phone import normalize_phone
from domain.models import Location, PatientIntake, PatientUpdate, valid_email
from domain.ports import Coordinates, PatientSession

ADDRESS_COLUMNS = ("address", "city", "state", "zip", "latitude", "longitude")
UNPLACEABLE = "no coordinates for that ZIP, so I cannot match clinics to it"


def reason_for(error: Exception) -> str:
    """Keep the original patient-facing constraint messages."""
    if "email" in str(error):
        return "that email is already registered to a different phone number"
    if "FOREIGN KEY" in str(error):
        return "that clinic or patient is not on file"
    return str(error)


class PatientService:
    def __init__(self, session: PatientSession, coordinates: Coordinates) -> None:
        self.session = session
        self.coordinates = coordinates

    def find(self, email: str, phone: str) -> dict | None:
        with self.session() as repository:
            return repository.find(email.strip(), normalize_phone(phone))

    def read(self, patient_id: int) -> dict:
        with self.session() as repository:
            return repository.read(patient_id)

    def register(self, intake: PatientIntake, place: Location) -> dict:
        values = {
            **intake.model_dump(mode="json"),
            **self.address(place),
            "complaints": "",
        }
        with self.session() as repository:
            if values["latitude"] is None:
                return {"ok": False, "error": f"{UNPLACEABLE}: {place.zip}"}
            try:
                patient_id = repository.insert(values)
            except StorageConflict as error:
                return {"ok": False, "error": reason_for(error)}
        return {"ok": True, "patient": self.read(patient_id)}

    def update(self, patient_id: int, changes: PatientUpdate | dict) -> dict:
        values = changes.changes() if isinstance(changes, PatientUpdate) else dict(changes)
        values = {name: value for name, value in values.items() if value is not None}
        if "email" in values:
            try:
                values["email"] = valid_email(values["email"])
            except ValueError:
                return {"ok": False, "error": "invalid email; use name@example.com"}
        if "phone" in values:
            try:
                values["phone"] = normalize_phone(values["phone"])
            except ValueError as error:
                return {"ok": False, "error": str(error)}
        if not values:
            return {"ok": True, "patient": self.read(patient_id)}
        with self.session() as repository:
            if values.get("zip") and self.coordinates(values["zip"]) is None:
                return {"ok": False, "error": f"{UNPLACEABLE}: {values['zip']}"}
            if set(values) & {"zip", "address"}:
                row = repository.location(patient_id)
                place = Location(**row) if row else None
                values.update(self.address(place, **values))
            try:
                repository.update(patient_id, values)
            except StorageConflict as error:
                return {"ok": False, "error": reason_for(error)}
        return {"ok": True, "patient": self.read(patient_id)}

    def replace_contacts(self, patient_id: int, email: str, phone: str,
                         expected: tuple[str, str | None]) -> dict:
        email, phone = valid_email(email.strip()), normalize_phone(phone)
        try:
            with self.session() as repo:
                if not repo.replace_contacts(patient_id, email, phone, expected):
                    return {"ok": False, "error": "The account changed while these details were being confirmed. Start a new chat and provide your current details."}
        except StorageConflict:
            return {"ok": False, "error": "Those contact details cannot be saved. Please check the email or contact the clinic."}
        return {"ok": True, "patient": self.read(patient_id)}

    def address(self, place: Location | None, **changes) -> dict:
        """Apply changed address fields and derive coordinates from the effective ZIP."""
        if place is None:
            return {}
        located = self.coordinates(changes.get("zip", place.zip))
        latitude, longitude = located if located is not None else (None, None)
        return {
            "address": place.address,
            "city": place.city,
            "state": place.state,
            "zip": place.zip,
            "latitude": latitude,
            "longitude": longitude,
            **changes,
        }