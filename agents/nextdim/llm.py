"""Thin OpenAI helper: ask for JSON that fits a pydantic model.

Pass `on_event` to watch a call. See app/trace.py for the event shape.
"""

import json

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.config import MODEL, OPENAI_API_KEY
from app.trace import MODEL as MODEL_EVENT
from app.trace import emit

# One try, then one retry carrying the validation error, so a reply that does
# not fit the model cannot move the conversation forward.
ATTEMPTS = 2


def ask(
    model: type[BaseModel],
    system: str,
    payload: dict,
    client=None,
    on_event=None,
    label: str = "",
) -> BaseModel:
    """Return `model` parsed from the reply to system + payload.

    One retry is made with the validation error if the reply does not fit, so a
    bad answer cannot move the conversation forward. `client` is anything with
    `chat.completions.create`, which lets tests pass a stub. `label` is the
    human wording of what is being asked, shown in the UI trace; `on_event`
    receives the request and every reply.
    """
    if client is None and not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")
    client = client or OpenAI()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload)},
    ]
    for attempt in range(1, ATTEMPTS + 1):
        emit(
            on_event,
            MODEL_EVENT,
            label or f"Fill in a {model.__name__}",
            step_detail=system,
            input=payload,
            model=MODEL,
            attempt=attempt,
        )
        reply = client.chat.completions.create(
            model=MODEL, response_format={"type": "json_object"}, messages=messages
        )
        content = reply.choices[0].message.content
        try:
            parsed = model.model_validate_json(content)
        except ValidationError as error:
            emit(
                on_event,
                NOTE,
                "The reply did not fit, asking again with the error",
                reply=content,
                error=str(error),
                attempt=attempt,
            )
            messages.append({"role": "assistant", "content": content})
            messages.append(
                {"role": "user", "content": f"Rejected: {error}. Reply with valid JSON only."}
            )
            continue
        emit(on_event, MODEL_EVENT, "The model answered", reply=content, output=parsed.model_dump(mode="json"))
        return parsed
    raise ValueError("the model did not return usable JSON")
