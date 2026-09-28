"""Untrusted language extraction models, separate from validated domain records."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IntakeDraft(BaseModel):
    """Contacts remain verbatim until application validation; never repair them."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    date_of_birth: date | None = None


class UpdateDraft(IntakeDraft):
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None


class BookingDecision(BaseModel):
    """Language intent only. The model can never create a booking or a slot."""

    model_config = ConfigDict(extra="forbid")
    intent: Literal["confirm", "change", "decline", "unclear"]
    option_number: int | None = Field(default=None, ge=1, le=99, strict=True)

    @model_validator(mode="after")
    def option_is_only_a_change(self):
        if self.option_number is not None and self.intent != "change":
            raise ValueError("An option number is permitted only for a change request")
        return self