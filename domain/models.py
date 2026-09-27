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
PHONE = re.compile(r"^\+?\d[\d \-]{6,19}$")


def valid_email(value: str) -> str:
    if not EMAIL.match(value):
        raise ValueError("invalid email")
    return value


def valid_phone(value: str) -> str:
    if not PHONE.match(value):
        raise ValueError("invalid phone number")
    return value

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
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

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
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    patient_id: int = Field(gt=0)
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    email: str
    phone: str
    date_of_birth: date
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
    def check_phone(cls, value: str) -> str:
        return valid_phone(value)


class Booking(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

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

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    description: str = Field(min_length=1)
    speciality: Speciality
    understood_as: str = Field(min_length=1)


class PatientIntake(BaseModel):
    """Details the portal collects before it can match or register a patient."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    email: str | None = None
    phone: str | None = None

    def missing(self) -> list[str]:
        """Field names that are still empty, in the order to ask for them."""
        return [
            name
            for name in ("first_name", "last_name", "date_of_birth", "email", "phone")
            if getattr(self, name) is None
        ]

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str | None) -> str | None:
        return valid_email(value) if value else value

    @field_validator("phone")
    @classmethod
    def check_phone(cls, value: str | None) -> str | None:
        return valid_phone(value) if value else value


class Location(BaseModel):
    """A postal address. Coordinates come from app.geo, never from the model."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    address: str = Field(min_length=1)
    city: str = Field(min_length=1)
    state: str = Field(min_length=2, max_length=2)
    zip: str = Field(pattern=r"^\d{5}$")


class Availability(BaseModel):
    """When the patient can come in."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    date: date
    period: Literal["morning", "afternoon", "evening", "any"] = "any"


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
