"""Pydantic models that validate CSV rows. Validation only, no app logic."""

import re
from datetime import date, time
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
from domain.phone import normalize_phone

# What a patient has to give before the portal can look them up, in the order it
# asks. The name is asked as two parts because that is how it is stored.
INTAKE_REQUIRED = ("first_name", "last_name", "email", "phone")

# A booking day that may not be there. Aliased because Availability carries a
# field called date, and a field name that shadows the type it is declared as
# cannot be annotated with that type directly.
OptionalDate = date | None

# The parts of a postal address, used to tell a change of address from a change
# of name or number.
LOCATION_FIELDS = ("address", "city", "state", "zip")


def valid_email(value: str) -> str:
    from domain.email import validate_email
    return validate_email(value)


def valid_phone(value: str) -> str:
    return normalize_phone(value)


Speciality = Literal[
    "cardiology",
    "ENT",
    "dermatology",
    "pediatrics",
    "orthopedics",
    "neurology",
    "gastroenterology",
    "ophthalmology",
    "urology",
    "gynecology",
    "psychiatry",
    "endocrinology",
    "pulmonology",
    "oncology",
    "general surgery",
    "nephrology",
    "rheumatology",
    "dentistry",
    "general practice",
]

BookingStatus = Literal["booked", "confirmed", "cancelled", "completed"]


class Clinic(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)

    clinic_id: int = Field(gt=0)
    name: str = Field(min_length=1)
    speciality: Speciality
    address: str = Field(min_length=1)
    city: str = Field(min_length=1)
    state: str = Field(min_length=2, max_length=2)
    zip: str = Field(min_length=5, max_length=5)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class Patient(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)

    patient_id: int = Field(gt=0)
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    email: str
    phone: str | None
    # Optional: the portal only asks a patient for what it needs to book them, and
    # a date of birth is not part of that.
    date_of_birth: date | None = None
    address: str = Field(min_length=1)
    city: str = Field(min_length=1)
    state: str = Field(min_length=2, max_length=2)
    zip: str = Field(min_length=5, max_length=5)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    complaints: str = Field(min_length=1)

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str) -> str:
        return valid_email(value)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, value: str | None) -> str | None:
        return valid_phone(value) if value is not None else None


class Booking(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)

    booking_id: int = Field(gt=0)
    clinic_id: int = Field(gt=0)
    patient_id: int = Field(gt=0)
    slot_date: date
    start_time: time
    end_time: time
    status: BookingStatus = "booked"

    @model_validator(mode="after")
    def check_slot(self) -> "Booking":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self

    @field_serializer("start_time", "end_time")
    def hhmm(self, value: time) -> str:
        """Times stay HH:MM so the database matches the slot strings of the tools."""
        return value.strftime("%H:%M")


class Complaint(BaseModel):
    """What the patient described, and what the agent understood by it."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)

    description: str = Field(min_length=1)
    speciality: Speciality
    understood_as: str = Field(min_length=1)
    detail: str = ""


class Confirmation(BaseModel):
    """Whether a patient is agreeing with what the agent just said, or not."""

    model_config = ConfigDict(extra="forbid")

    agreed: bool


class SlotPick(BaseModel):
    """Which of the slots a patient was shown their reply means, if any."""

    model_config = ConfigDict(extra="forbid")

    number: int | None = Field(default=None, ge=1, le=99)
    another_time: bool = False


class PatientIntake(BaseModel):
    """Details the portal collects before it can look a patient up.

    Name, phone and email are what a patient is identified by, so those are the
    three the portal asks for. A date of birth is kept when a patient offers it
    and left empty when they do not, rather than being asked for.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)

    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    date_of_birth: date | None = None

    def missing(self) -> list[str]:
        """Field names that are still empty, in the order to ask for them."""
        return [name for name in INTAKE_REQUIRED if getattr(self, name) is None]

    def full_name(self) -> str:
        """The name to greet the patient by, whichever part of it is known."""
        return " ".join(part for part in (self.first_name, self.last_name) if part) or "there"

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str | None) -> str | None:
        return valid_email(value) if value else value

    @field_validator("phone")
    @classmethod
    def check_phone(cls, value: str | None) -> str | None:
        return valid_phone(value) if value else value


class PatientUpdate(BaseModel):
    """A correction to the record on file. Whatever is not mentioned is left alone."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)

    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    date_of_birth: date | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None

    def changes(self) -> dict:
        """Only the fields the message actually carried, ready to be written."""
        return {name: value for name, value in self.model_dump().items() if value is not None}

    def moves(self) -> bool:
        """Does the message change where the patient lives, rather than who they are?"""
        return any(getattr(self, name) is not None for name in LOCATION_FIELDS)

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str | None) -> str | None:
        return valid_email(value) if value else value

    @field_validator("phone")
    @classmethod
    def check_phone(cls, value: str | None) -> str | None:
        return valid_phone(value) if value else value

    @field_validator("state")
    @classmethod
    def check_state(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class Location(BaseModel):
    """A postal address. Coordinates come from app.geo, never from the model."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)

    address: str = Field(min_length=1)
    city: str = Field(min_length=1)
    state: str = Field(min_length=2, max_length=2)
    zip: str = Field(pattern=r"^\d{5}$")


class Availability(BaseModel):
    """When the patient would like to be seen.

    `date` is the one open day the model matched what the patient said against,
    so it is left empty rather than guessed at when they asked for a day that is
    not on the list. `outside` says that outright, which is what lets the agent
    tell the patient the booking window ends rather than quietly moving them
    into a day they did not ask for. `weekday` is the day of the week they named
    in their own words, kept so it can be read back to them next to the date it
    resolved to.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)

    date: OptionalDate = None
    end_date: OptionalDate = None
    weekday: str = ""
    period: Literal["morning", "afternoon", "evening", "any"] = "any"
    # A time of day the patient insisted on, if they gave one, in 24 hour form.
    at: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    outside: bool = False


class SlotOption(BaseModel):
    """One bookable choice offered to the patient."""

    clinic_id: int
    clinic_name: str
    speciality: str
    distance_km: float
    date: date
    start_time: time
    end_time: time
    reason: str = ""
    # The zone the clinic keeps its clock in, so the time shown to the patient is
    # the time they will be seen at rather than a time shifted by a timezone.
    zone: str = ""

    @classmethod
    def from_row(cls, row: dict) -> "SlotOption":
        """Build an option from one row of tools.rank_slots."""
        return cls(
            clinic_id=row["clinic_id"],
            clinic_name=row["name"],
            speciality=row["speciality"],
            distance_km=row["distance_km"],
            date=date.fromisoformat(row["date"]),
            start_time=time.fromisoformat(row["start_time"]),
            end_time=time.fromisoformat(row["end_time"]),
            reason=row.get("reason", ""),
            zone=row.get("zone", ""),
        )