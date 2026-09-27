"""HTTP API for chatting with the agent, and the page that shows the steps.

A turn returns the agent's reply plus the events it emitted, so the browser can
show what the agent did before showing what it said.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import MODEL, OPENAI_API_KEY, VERSION
from app.sessions import drop_session, get_session, new_session

router = APIRouter()

INDEX = Path(__file__).parent / "static" / "index.html"


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


class ResetOut(BaseModel):
    """A fresh conversation and its opening message."""

    session_id: str
    reply: str


@router.get("/", include_in_schema=False)
def index() -> FileResponse:
    """The chat page."""
    return FileResponse(INDEX)


@router.post("/api/reset", response_model=ResetOut)
def reset(payload: dict) -> ResetOut:
    """Throw the conversation away and start a new one."""
    drop_session(payload.get("session_id") or "")
    session_id, agent = new_session()
    return ResetOut(session_id=session_id, reply=agent.start())


@router.post("/api/chat", response_model=TurnOut)
def chat(payload: ChatIn) -> TurnOut:
    """Send one message and return the reply with the steps that led to it."""
    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not set. Copy .env.example to .env, put your key in "
            "it, and restart the server.",
        )

    events: list[dict] = []
    agent = get_session(payload.session_id) if payload.session_id else None
    if agent is None:
        # No session yet: this agent has no on_event, so point it at the list.
        session_id, agent = new_session(on_event=events.append)
    else:
        session_id = payload.session_id
        # Re-point at this request's list, so a turn only reports its own steps.
        agent.on_event = events.append

    try:
        reply = agent.handle(payload.message)
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except ValueError as error:
        # The model could not produce usable JSON, so the step was abandoned.
        raise HTTPException(status_code=502, detail=f"The model could not be used: {error}") from error

    return TurnOut(
        session_id=session_id,
        reply=reply,
        step=agent.step,
        done=agent.step == "done",
        events=events,
        booking=agent.booking,
    )


@router.get("/api/config")
def config() -> dict:
    """What the page needs to tell the user before they start chatting."""
    return {"version": VERSION, "model": MODEL, "ready": bool(OPENAI_API_KEY)}
