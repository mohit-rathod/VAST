"""Tool: suggest the best clinics for a patient, using OpenAI.

Distance is worked out here (a language model should not do arithmetic), then the
nearest clinics and their free slots are handed to the model, which picks the
top 3 by speciality match and availability.
"""

import json

from openai import OpenAI

from app.config import MODEL, OPENAI_API_KEY
from app.db import connect
from app.geo import zone_name_of
from app.trace import MODEL as MODEL_KIND
from app.trace import NOTE, TOOL, emit
from repositories.clinics import SQLiteClinicRepository
from services.clinics import ClinicService, distance_km

from .available_slots import available_slots

SHORTLIST = 8

SYSTEM = (
    "You triage a patient to clinics in New York. Reply with JSON only, shaped as"
    ' {"clinics": [{"clinic_id": int, "reason": str, "suggested_slots": ["HH:MM-HH:MM"]}]}.'
    " Order the clinics best first and return at most 3. Choose clinics whose"
    " speciality matches the complaint, that are close to the patient, and that have"
    " free slots on the requested date. Only use clinic ids and slots from the"
    " candidates given to you, never invent them."
)


def _service() -> ClinicService:
    return ClinicService(SQLiteClinicRepository(connect), available_slots, zone_name_of, distance_km)


def nearest_clinics(
    patient_id: int, count: int | None = SHORTLIST, speciality: str | None = None
) -> list[dict]:
    """The closest clinics, optionally limited and filtered by speciality."""
    return _service().nearest(patient_id, count, speciality)


def nearest_candidates(patient_id: int, day, count: int = SHORTLIST) -> tuple[dict, list[dict]]:
    """The patient and nearest clinics, with their free slots on the given day."""
    return _service().candidates(patient_id, day, count)


def suggest_clinics(patient_id: int, day, limit: int = 3, client=None, on_event=None) -> list[dict]:
    """Top clinics for a patient: nearest ones first, ranked by the LLM.

    `day` is the date the patient wants, and `limit` is how many to return. The
    model only picks ids and gives a reason; the name, speciality, distance and
    free slots are filled in here from the shortlist, so every returned row is
    complete and no invented id can slip through. `client` is any object with
    `chat.completions.create`, so it can be swapped in tests. `on_event` follows
    app/trace.py and receives the shortlist, the ranking call and the result.
    """
    if client is None and not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")

    patient, candidates = nearest_candidates(patient_id, day)
    emit(
        on_event,
        TOOL,
        f"Worked out the {len(candidates)} nearest clinics by straight line distance",
        patient=f'{patient["first_name"]} {patient["last_name"]}',
        complaints=patient["complaints"],
        day=str(day),
        candidates=[
            f'{c["name"]} ({c["speciality"]}, {c["distance_km"]} km, {len(c["free_slots"])} free)'
            for c in candidates
        ],
    )
    payload = {
        "patient": {
            "name": f'{patient["first_name"]} {patient["last_name"]}',
            "complaints": patient["complaints"],
            "address": f'{patient["address"]}, {patient["city"]} {patient["zip"]}',
        },
        "requested_date": str(day),
        "candidates": candidates,
    }
    client = client or OpenAI()
    emit(
        on_event,
        MODEL_KIND,
        "Ask the model to rank that shortlist by speciality and free slots",
        step_detail=SYSTEM,
        input=payload,
        model=MODEL,
    )
    reply = client.chat.completions.create(
        model=MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(payload)},
        ],
    )
    content = reply.choices[0].message.content
    emit(on_event, MODEL_KIND, "The model replied", reply=content)
    picks = json.loads(content)["clinics"]

    known = {candidate["clinic_id"]: candidate for candidate in candidates}
    chosen = []
    for pick in picks[:limit]:
        candidate = known.get(pick.get("clinic_id"))
        if candidate is None:
            emit(
                on_event,
                NOTE,
                f'Dropped clinic {pick.get("clinic_id")}, it was not in the shortlist',
            )
            continue
        chosen.append(
            {
                **candidate,
                "reason": pick.get("reason", ""),
                "suggested_slots": pick.get("suggested_slots", []),
            }
        )
    return chosen
