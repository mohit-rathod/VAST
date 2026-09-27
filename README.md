# VAST

**Version 0.1.0**

Voice Automated Scheduling Technology

Python backend: FastAPI + SQLite, with tools for slots, booking and clinic matching.

VAST is a clinic appointment portal. A patient describes a problem in their own
words, the agent works out the speciality, registers or looks them up, finds a
clinic near them with a free slot and books it. The model does the language
work; the calendar, the arithmetic and the database work are plain code.

| | |
| --- | --- |
| Stack | Python 3.11, FastAPI, SQLite, Pydantic, OpenAI |
| Entry points | `make run` for the chat UI, `make agent` for the terminal |
| Database | `data/vast.db`, built from the CSVs in `data/` by `make ingest` |
| Tests | none yet, the tools are small enough to call from a Python shell |

## Setup

```bash
make venv
make install
cp .env.example .env      # then put your OpenAI key in .env
```

`.env` holds `OPENAI_API_KEY` and, if you want a different one, `VAST_MODEL`.
It is gitignored; `app/config.py` reads it and every module imports the settings
from there, so the key never has to be exported by hand.

## Run

```bash
make run     # chat UI on http://127.0.0.1:8000, API docs at /docs
```

## Chat UI

`make run` serves a one page chat at http://127.0.0.1:8000. Type a complaint,
answer the questions, pick a clinic. It is the same `NextDimAgent` the
terminal uses, so anything you can do in one you can do in the other.

Each turn shows a **trace** above the reply, so you can see the work rather than
just the answer. Expand a turn to get every event, in order:

| badge | what it means |
| --- | --- |
| `step` | which part of the conversation machine is running |
| `model` | an OpenAI call: the input it was given, the raw reply, the parsed result |
| `tool` | plain code: the patient lookup, ZIP to coordinates, free slots, the booking |
| `note` | something worth knowing, like a reply that failed validation and was retried |

A retry shows up as its own `note`, followed by the second `model` call, so you
can see the bad JSON *and* the correction. Expand any event to see the exact
values.

The page is plain HTML, CSS and JavaScript in `app/static/index.html` with no
build step. It talks to three endpoints:

| endpoint | what it does |
| --- | --- |
| `POST /api/chat` | one message in, the reply plus the turn's events out |
| `POST /api/reset` | throw the conversation away and start a new one |
| `GET /api/config` | the model in use, and whether a key is set |

Each browser tab gets its own agent, held in memory by `app/sessions.py` and
lost on restart. The patients and bookings it writes go to SQLite as usual.
Without a key the page says so up front and `POST /api/chat` answers `503` with
the same message, rather than failing halfway through a booking.

## Data

`data/` holds the source CSVs and the SQLite file (`data/vast.db`, gitignored,
created automatically by `make ingest`).

| file | rows | columns |
| --- | --- | --- |
| `clinics.csv` | 20 | `clinic_id, name, speciality, address, city, state, zip, latitude, longitude` |
| `patients.csv` | 100 | `patient_id, first_name, last_name, email, phone, date_of_birth, address, city, state, zip, latitude, longitude, complaints` |
| `bookings.csv` | 1120 | `booking_id, clinic_id, patient_id, slot_date, start_time, end_time, status` |

All clinics are in the New York area, each with a speciality (cardiology, ENT,
dermatology, ...). Patients carry an address, coordinates and complaints, so they
can be matched to a clinic by speciality, complaint and distance.

Slot window: 30/09/2026 to 04/10/2026, 09:00-17:00, 30-minute slots.
20 clinics x 5 days x 16 slots = 1600 open slots, 1120 booked (70%).

## Ingest

```bash
make ingest      # python -m app.ingest
make reingest    # drop the database, then ingest
```

Every row is validated by its model in `domain/models.py` before it is inserted
(`app/ingest.py`), and inserts use `INSERT OR REPLACE`, so re-running is safe.
`UNIQUE (clinic_id, slot_date, start_time)` stops two bookings in one slot.

## The NextDim agent

```bash
make agent    # python -m agents.nextdim.agent
```

One step machine in `agents/nextdim/agent.py`. The model only does language work;
everything else is code:

| step | who | what happens |
| --- | --- | --- |
| 1 welcome | code | greeting |
| 2 complaint | LLM | restates the problem, names the speciality, asks the patient to confirm; "no" sends them back to explain again |
| 3 details | LLM + code | pulls name, date of birth, email, phone out of free text, re-asks for what is missing, then looks the patient up by **email + phone together**; an existing record is reused (name and date of birth are never overwritten), a new address registers them |
| 4 match | tools | asks for the date and morning/afternoon, then `suggest_clinics` + `available_slots` offer up to 3 clinic + slot choices. If that period is full, see below |
| 5 book | code | reads the choice back, and on "yes" calls `book_appointment`, then confirms with the booking id |

### When the time the patient asked for is full

If nothing is free in the period the patient asked for, the agent says so and
offers the closest other times instead of sending them back to re-ask:

```
Everything in the morning on 2026-09-30 is already booked. The closest I can get is:
1. Park Slope Pediatrics - pediatrics, 7.3 km away, 2026-09-30 13:00 to 13:30
2. Brooklyn Orthopedic Institute - orthopedics, 8.0 km away, 2026-09-30 12:00 to 12:30
3. Brooklyn ENT & Hearing Center - ENT, 8.4 km away, 2026-09-30 15:30 to 16:00
Which one would you like? Reply with the number.
```

They are the usual numbered choices, so picking one and confirming books it
normally. `alternatives` in `agents/nextdim/agent.py` sets the order, closest
first: another time on the same day before another day, because moving an
appointment within a day is easier than moving it to a different one, and among
the other days the nearest first, a later day winning a tie. So a request for
the middle of the window is never answered with the far end of it.

The search reuses `nearest_clinics`, which ranks by distance and needs no model
call, and looks up the whole window once per clinic. Widening the search
therefore costs one pass over the database, not a second OpenAI call, and only
the 3 that are shown are kept, so the number the patient replies with always
matches the list they were given. If the entire window is booked, the agent says
so and asks them to try again later.

Note that clinics open 09:00 to 17:00, so the **evening** period can never be
booked. Asking for it now lands in the fallback rather than dead-ending.

The location is always read back before moving on ("Let me confirm: 88 Berry St,
Brooklyn, NY 11211. Is that correct?"), and the ZIP is turned into coordinates by
`app/geo.py`, a small stand-in for a geocoding service covering the 20 New York
ZIPs in the data. Swap it for a real geocoding call when you have a key.

Every model reply is parsed into a pydantic model (`agents/nextdim/llm.py` retries
once with the validation error), so a malformed answer cannot move the
conversation forward.

Agents live one per folder under `agents/`, so a second one is just
`agents/<name>/` with its own prompts. When there is more than one, move
`llm.py` up to `agents/llm.py` and the folder that shares it.

## Tools

```python
from tools.available_slots import available_slots
from tools.book import book_appointment
from tools.match_clinics import suggest_clinics

available_slots(clinic_id=4)                 # free slots, whole window
available_slots(clinic_id=4, day="2026-09-30")   # free slots, one day
book_appointment(clinic_id=4, patient_id=7, slot_date="2026-09-30", start_time="09:30")
suggest_clinics(patient_id=7, day="2026-09-30", limit=3)   # needs OPENAI_API_KEY
```

Same three from the command line:

```bash
make slots CLINIC=4 DATE=2026-09-30
make book  CLINIC=4 PATIENT=7 DATE=2026-09-30 TIME=09:30
make match PATIENT=7 DATE=2026-09-30
```

`book_appointment` returns `{"ok": False, "error": ...}` if the slot is taken, is
not a real slot, or the patient/clinic is unknown. Three things stop two
concurrent callers from taking the same slot: the `threading.Lock` in
`tools/book.py`, `BEGIN IMMEDIATE` (SQLite write lock taken before reading), and
the UNIQUE index. A race ends with one `ok: True` and the rest
`UNIQUE constraint failed`.

`suggest_clinics` sorts clinics by real distance (haversine, in
`tools/match_clinics.py`) and sends the nearest 8 with their free slots to the
LLM, which returns JSON: `[{"clinic_id", "reason", "suggested_slots"}, ...]`. The
name, speciality and distance are filled back in from the shortlist, so an id
the model invented is dropped rather than shown. Override the model with
`VAST_MODEL`. Because the shortlist is distance-based, a speciality that only
exists far away is not offered.

`nearest_clinics` is the same distance ranking without the model call or the
day, which is what the fully-booked fallback uses.

## Layout

```
app/config.py      settings from the environment or .env
app/db.py          connection helper (connect, init_db) + schema
app/geo.py         New York ZIP -> coordinates (stand-in for a geocoder)
app/ingest.py      validate + load data/*.csv into SQLite
app/main.py        FastAPI app
app/chat.py        the chat endpoints, returning the reply with its trace
app/sessions.py    one agent per browser tab, in memory
app/trace.py       the event shape the agent and tools report on
app/static/index.html  the chat page
domain/models.py   pydantic models: Clinic, Patient, Booking, Complaint,
                   PatientIntake, Location, Availability, SlotOption
agents/nextdim/agent.py  the NextDim portal conversation
agents/nextdim/llm.py    OpenAI -> JSON that fits a pydantic model
tools/available_slots.py  free slots of a clinic
tools/book.py             book a slot, locked
tools/match_clinics.py    nearest clinics ranked by OpenAI
Makefile          venv, install, run, agent, ingest, slots, book, match, reset, clean
```

## Versions

| version | what it added |
| --- | --- |
| 0.1.0 | first release: the NextDim conversation, the three tools, the chat UI and the trace |
