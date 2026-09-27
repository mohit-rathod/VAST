"""Tool: suggest the best clinics for a patient, using OpenAI.

Distance is worked out here (a language model should not do arithmetic), then the
nearest clinics and their free slots are handed to the model, which picks the
top 3 by speciality match and availability.
"""

import json
import math

from openai import OpenAI

from app.config import MODEL, OPENAI_API_KEY
from app.db import connect
from app.trace import MODEL as MODEL_KIND
from app.trace import NOTE, TOOL, emit

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


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points."""
    lat1, lon1, lat2, lon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    half = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(
        (lon2 - lon1) / 2
    ) ** 2
    return 6371 * 2 * math.asin(math.sqrt(half))


def nearest_clinics(patient_id: int, count: int | None = SHORTLIST) -> list[dict]:
    """The `count` clinics closest to a patient, nearest first.

    Distance does not depend on the day, so a caller can rank the clinics once
    and then look up free slots for as many days as it likes. Pass `count` as
    None for every clinic. The agent uses this to offer nearby times when the
    period the patient asked for is fully booked, so it never has to pay for a
    second ranking call.
    """
    with connect() as conn:
        patient = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
        if patient is None:
            raise ValueError(f"no patient {patient_id}")
        clinics = conn.execute("SELECT * FROM clinics").fetchall()

    def distance(clinic) -> float:
        return distance_km(
            patient["latitude"],
            patient["longitude"],
            clinic["latitude"],
            clinic["longitude"],
        )

    ranked = sorted(clinics, key=distance)
    return [
        {
            "clinic_id": clinic["id"],
            "name": clinic["name"],
            "speciality": clinic["speciality"],
            "address": f'{clinic["address"]}, {clinic["city"]}, {clinic["state"]} {clinic["zip"]}',
            "distance_km": round(distance(clinic), 1),
        }
        for clinic in (ranked if count is None else ranked[:count])
    ]


def nearest_candidates(patient_id: int, day, count: int = SHORTLIST) -> tuple[dict, list[dict]]:
    """The patient and the `count` closest clinics, each with its free slots that day."""
    with connect() as conn:
        patient = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
    candidates = []
    for clinic in nearest_clinics(patient_id, count):
        free = available_slots(clinic["clinic_id"], day)
        candidates.append(
            {
                **clinic,
                "free_slots": [f'{slot["start_time"]}-{slot["end_time"]}' for slot in free],
            }
        )
    return dict(patient), candidates


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
