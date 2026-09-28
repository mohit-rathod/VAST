"""HTTP API for chatting with the agent, and the page that shows the steps.

A turn returns the agent's reply plus the events it emitted, so the browser can
show what the agent did before showing what it said.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.config import MODEL, OPENAI_API_KEY, VERSION
from app import sessions
from app.schemas import ChatIn, ResetOut, TurnOut
from domain.errors import AgentRuntimeFailure, AgentValueFailure
from services.chat import ChatService
from agents.nextdim.controls import is_end_request

router = APIRouter()
service = ChatService(sessions)

INDEX = Path(__file__).parent / "static" / "index.html"


@router.get("/", include_in_schema=False)
def index() -> FileResponse:
    """The chat page."""
    return FileResponse(INDEX)


@router.get("/static/chat-actions.js", include_in_schema=False)
def chat_actions_script() -> FileResponse:
    """Serve only this known frontend asset, not arbitrary filesystem paths."""
    return FileResponse(INDEX.parent / "chat-actions.js", media_type="text/javascript")


@router.post("/api/reset", response_model=ResetOut)
def reset(payload: dict) -> ResetOut:
    """Throw the conversation away and start a new one."""
    return ResetOut(**service.reset(payload.get("session_id") or ""))


@router.post("/api/chat", response_model=TurnOut)
def chat(payload: ChatIn, request: Request) -> TurnOut:
    """Send one message and return the reply with the steps that led to it."""
    if not OPENAI_API_KEY and not is_end_request(payload.message) and payload.message.strip().lower() not in {"yes", "no"}:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not set. Copy .env.example to .env, put your key in "
            "it, and restart the server.",
        )

    try:
        resolve_actions = request.headers.get("x-resolve-actions") == "1"
        result = service.turn(payload.session_id, payload.message, resolve_actions=resolve_actions)
    except AgentRuntimeFailure as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except AgentValueFailure as error:
        # The model could not produce usable JSON, so the step was abandoned.
        raise HTTPException(status_code=502, detail=f"The model could not be used: {error}") from error

    return TurnOut(**result)


@router.get("/api/config")
def config() -> dict:
    """What the page needs to tell the user before they start chatting."""
    return {"version": VERSION, "model": MODEL, "ready": bool(OPENAI_API_KEY)}