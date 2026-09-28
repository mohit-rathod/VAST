"""Throwaway: drive the whole conversation with a stub model client."""

import json
import sqlite3
import threading
from types import SimpleNamespace

from agents.nextdim.agent import NextDimAgent
from domain.models import PatientIntake
from tools.book import book_appointment
from tools.patients import read

INTAKE = "Pull the patient's details"
UPDATE = "correcting what the portal already has"
COMPLAINT = "intake assistant"
CONFIRMING = "An agent has checked something"
SLOT = "A patient has been shown a numbered list"
PREFERENCE = "Work out when the patient would like"

SCRIPT = {}


class Stub:
    """Answers with whatever SCRIPT says for the prompt it recognises."""

    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.seen = []

    def create(self, model, response_format, messages):
        system = messages[0]["content"]
        payload = json.loads(messages[1]["content"])
        self.seen.append((model, system[:20]))
        for marker, reply in SCRIPT.items():
            if marker in system:
                content = reply(payload) if callable(reply) else reply
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(content)))]
                )
        raise AssertionError(f"no stub for {system[:60]}")


def say(agent, message, note=""):
    reply = agent.handle(message)
    print(f"\n> {message}\n{reply}")
    if note:
        print(f"   [{agent.step}] {note}")
    return reply


def scenario(title, script, turns, patient_id=None):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)
    SCRIPT.clear()
    SCRIPT.update(script)
    events = []
    agent = NextDimAgent(client=Stub(), on_event=events.append)
    print(agent.start())
    for turn in turns:
        say(agent, turn)
    print(f"\nstep={agent.step} booking={agent.booking}")
    if patient_id:
        print("record:", {k: read(patient_id)[k] for k in ("first_name", "email", "phone", "zip", "complaints")})
    print("model calls:", len(agent.context.client.seen))
    return agent


NEW = {
    INTAKE: {
        "first_name": "Jane",
        "last_name": "Doe",
        "email": "jane.doe@example.com",
        "phone": "+1-555-0100",
        "date_of_birth": None,
    },
    UPDATE: {
        "first_name": None,
        "last_name": None,
        "email": None,
        "phone": None,
        "date_of_birth": None,
        "address": "12 Main St",
        "city": "Brooklyn",
        "state": "NY",
        "zip": "11215",
    },
    COMPLAINT: {
        "description": "chest pain on the left side",
        "speciality": "cardiology",
        "understood_as": "You have pain on the left side of your chest.",
        "detail": "started two weeks ago",
    },
    CONFIRMING: {"agreed": False},
    SLOT: {"number": None, "another_time": True},
    PREFERENCE: {"date": "2026-10-01", "period": "morning", "at": None},
}

scenario(
    "1. new patient, straight through",
    NEW,
    [
        "I am Jane Doe, jane.doe@example.com, 555-0100",
        "12 Main St, Brooklyn, NY 11215",
        "yes",
        "yes that is right",
        "I have chest pain on my left side",
        "yes",
        "Tuesday morning please",
        "2",
        "yes",
    ],
)

scenario(
    "2. complaint loop: not understood, then more detail, then agreed",
    {
        **NEW,
        COMPLAINT: lambda p: (
            {
                "description": "chest pain on the left side",
                "speciality": "cardiology",
                "understood_as": "You have pain on the left side of your chest.",
                "detail": "started two weeks ago",
            }
            if "already_understood" not in p
            else {
                "description": "chest pain on the left side, worse when I walk uphill",
                "speciality": "cardiology",
                "understood_as": (
                    "You have left-sided chest pain that started two weeks ago and gets"
                    " worse when you walk uphill."
                ),
                "detail": "radiates into the jaw, comes and goes",
            }
        ),
        PREFERENCE: {"date": "2026-09-30", "period": "afternoon", "at": "14:00"},
        # Confirmed in the patient's own words, not with a "yes".
        CONFIRMING: lambda p: {"agreed": "my problem" in p["message"]},
    },
    [
        "I am Jane Doe, jane.doe@example.com, 555-0100",
        "12 Main St, Brooklyn, NY 11215",
        "correct",
        "my chest hurts",
        "no, that is not it",
        "it is on the left and I get dizzy climbing stairs",
        "no",
        "it also goes into my jaw",
        "that is exactly my problem",
        "Wednesday afternoon around 2pm",
        "1",
        "yes",
    ],
)

scenario(
    "3. slot loop: ask for another day, then another time, then agree",
    {
        **NEW,
        PREFERENCE: lambda p: {
            "date": "2026-09-30" if p["message"].count("morning") else "2026-10-02",
            "period": "morning" if "morning" in p["message"] else "evening",
            "at": None,
        },
    },
    [
        "I am Jane Doe, jane.doe@example.com, 555-0100",
        "12 Main St, Brooklyn, NY 11215",
        "yes",
        "yes",
        "sharp pain in my right ear",
        "yes",
        "any morning",
        "can I have Thursday instead",
        "actually an evening appointment",
        "the first one then",
        "go ahead",
    ],
    patient_id=3,
)

RETURNING = {
    **NEW,
    INTAKE: {
        "first_name": "Mei",
        "last_name": "Costa",
        "email": "mei.costa1@example.com",
        "phone": "+1-555-1001",
        "date_of_birth": "1993-01-28",
    },
    UPDATE: {
        "first_name": None,
        "last_name": None,
        "email": None,
        "phone": None,
        "date_of_birth": None,
        "address": "88 Berry St, Apt 4",
        "city": "Brooklyn",
        "state": "NY",
        "zip": "11249",
    },
}

scenario(
    "4. registered patient: details read back, address updated, problem, booked",
    RETURNING,
    [
        "Mei Costa, mei.costa1@example.com, +1-555-1001",
        "I have moved to 88 Berry St Apt 4, Brooklyn NY 11249",
        "yes",
        "yes",
        "my nose has been blocked for weeks",
        "yes",
        "Thursday afternoon",
        "1",
        "yes",
    ],
)

scenario(
    "5. missing details and a day outside the window",
    {
        **NEW,
        INTAKE: lambda p: (
            {"first_name": "Jane", "last_name": None, "email": None, "phone": "+1-555-0100", "date_of_birth": None}
            if p["message"] == "it is Jane"
            else NEW[INTAKE]
        ),
        PREFERENCE: lambda p: (
            {"date": "2027-01-04", "period": "any", "at": None}
            if "March" in p["message"]
            else {"date": "2026-10-01", "period": "any", "at": None}
        ),
    },
    [
        "it is Jane",
        "Jane Doe, jane.doe@example.com",
        "12 Main St, Brooklyn, NY 11215",
        "yes",
        "yes",
        "I have chest pain",
        "yes",
        "sometime in March 2027",
        "next Friday",
        "1",
        "yes",
    ],
)

print("\n" + "=" * 78)
print("6. two candidates, one slot")
print("=" * 78)
free = [
    slot
    for slot in __import__("tools.available_slots", fromlist=["x"]).available_slots(1, "2026-10-04")
    if slot["start_time"] == "16:30"
]
print("free before:", free)
results = []
barrier = threading.Barrier(8)


def grab(index):
    barrier.wait()
    results.append(book_appointment(1, 10 + index, "2026-10-04", "16:30"))


threads = [threading.Thread(target=grab, args=(n,)) for n in range(8)]
[t.start() for t in threads]
[t.join() for t in threads]
won = [r for r in results if r["ok"]]
print("attempts:", len(results), "booked:", len(won), "errors:", sorted({r.get("error") for r in results if not r["ok"]}))
print("bookings on that slot:", conn_rows() if False else "")
with sqlite3.connect("data/vast.db") as conn:
    print(
        "rows for clinic 1 on 2026-10-04 16:30:",
        conn.execute(
            "SELECT COUNT(*), GROUP_CONCAT(patient_id) FROM bookings"
            " WHERE clinic_id = 1 AND slot_date = '2026-10-04' AND start_time = '16:30'"
        ).fetchone(),
    )

print("\n" + "=" * 78)
print("7. bad model reply is caught")
print("=" * 78)
SCRIPT.clear()
SCRIPT[INTAKE] = {"first_name": "Jane"}
SCRIPT[UPDATE] = NEW[UPDATE]
agent = NextDimAgent(client=Stub())
print(agent.start())
print(">", agent.handle("I am Jane Doe, jane.doe@example.com, 555-0100"))
print(PatientIntake(first_name="A", last_name="B", email="a@b.co", phone="+1-555-0100").missing())
print("read of a patient nobody updated:", read(99999))
print("find of nobody:", __import__("tools.patients", fromlist=["x"]).find_patient("no@one.co", "+1-555-0000"))
