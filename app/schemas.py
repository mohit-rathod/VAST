"""HTTP request and response contracts, re-exported by app.chat for compatibility."""

from pydantic import BaseModel, Field


class ChatIn(BaseModel):
    """One patient message, and the conversation it belongs to."""

    session_id: str | None = None
    message: str = Field(min_length=1, max_length=2000)


class TurnOut(BaseModel):
    """The agent's reply, plus everything it did to get there."""

    session_id: str
    reply: str
    step: str
    done: bool
    events: list[dict]
    booking: dict | None = None
    actions: list[dict[str, str]] = Field(default_factory=list)
    bookings: list[dict] | None = None


class ResetOut(BaseModel):
    """A fresh conversation and its opening message."""

    session_id: str
    reply: str