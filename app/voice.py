"""Create a browser Realtime connection; the existing /api/chat owns agent turns."""

import json
import logging
import os
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request as UpstreamRequest, urlopen

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app import config, sessions

router = APIRouter()
logger = logging.getLogger(__name__)
REALTIME_URL = "https://api.openai.com/v1/realtime/calls"


class VoiceSessionIn(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    sdp: str = Field(min_length=20, max_length=65536)


@router.get("/static/voice.js", include_in_schema=False)
def voice_script() -> FileResponse:
    return FileResponse(
        Path(__file__).parent / "static" / "voice.js",
        media_type="text/javascript",
    )


@router.post("/api/voice/session")
def create_voice_session(payload: VoiceSessionIn, request: Request) -> Response:
    # Exact browser-origin allowlist. This is NOT a replacement for authentication.
    allowed_origins = {
        value.strip().rstrip("/")
        for value in os.getenv(
            "VAST_VOICE_ALLOWED_ORIGINS",
            "http://localhost:8000,http://127.0.0.1:8000",
        ).split(",")
        if value.strip()
    }
    if request.headers.get("origin") not in allowed_origins:
        raise HTTPException(403, "This browser origin is not allowed for voice.")
    if not config.OPENAI_API_KEY:
        raise HTTPException(503, "OPENAI_API_KEY is not set. Restart after setting it.")
    if sessions.get_session(payload.session_id) is None:
        raise HTTPException(409, "Chat session expired. Start a new chat first.")
    if not payload.sdp.startswith("v=0"):
        raise HTTPException(422, "Invalid WebRTC SDP offer.")

    session = {
        "type": "realtime",
        "model": config.REALTIME_MODEL,
        "output_modalities": ["audio"],
        "instructions": (
            "You are the voice I/O layer for an application whose backend owns the "
            "conversation, reasoning, and business actions. Follow the task given on "
            "each response: transcription tasks return a faithful transcript; speech "
            "tasks read the backend's finalized reply. Do not add a separate assistant "
            "answer or commentary."
        ),
        "tools": [],
        "tool_choice": "none",
        "audio": {
            "input": {
                "noise_reduction": {"type": "near_field"},
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 850,
                    "create_response": False,
                    "interrupt_response": False,
                },
            },
            "output": {"voice": config.REALTIME_VOICE},
        },
    }
    # Standard-library multipart request: no additional Python dependency.
    boundary = "voice_" + uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="sdp"\r\n'
        "Content-Type: application/sdp\r\n\r\n"
        f"{payload.sdp}\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="session"\r\n'
        "Content-Type: application/json\r\n\r\n"
        f"{json.dumps(session)}\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    upstream = UpstreamRequest(
        REALTIME_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urlopen(upstream, timeout=25) as result:
            answer = result.read(262145)
    except HTTPError as error:
        # Do not expose credentials, patient content, SDP or raw upstream bodies.
        logger.warning("Realtime session creation failed: status=%s", error.code)
        status = 429 if error.code == 429 else 502
        raise HTTPException(
            status,
            "OpenAI could not start voice. Check the server API key, access to "
            "gpt-realtime, quota, and voice/model configuration.",
        ) from error
    except TimeoutError as error:
        raise HTTPException(504, "OpenAI voice connection timed out.") from error
    except URLError as error:
        raise HTTPException(502, "Could not connect to OpenAI for voice.") from error

    if len(answer) > 262144 or not answer.startswith(b"v=0"):
        raise HTTPException(502, "OpenAI returned an invalid WebRTC answer.")
    return Response(
        content=answer,
        media_type="application/sdp",
        headers={"Cache-Control": "no-store"},
    )