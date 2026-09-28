# VAST / NextDim — v0.2.3

### Working Video Demo

[▶️ Click here to watch/download the working demo video (vast.mp4)](https://github.com/mohit-rathod/VAST/raw/main/vast.mp4)

*FastAPI healthcare scheduling agent with typed chat and real-time voice interface.*

---


# VAST / NextDim — v0.2.3

FastAPI healthcare scheduling demo with a stateful `NextDimAgent`, SQLite, typed chat, and OpenAI `gpt-realtime` voice. Voice is an interface only: STT feeds the same `/api/chat` path as typed text, and TTS speaks the agent's completed reply.

## 1. Setup

Prerequisites: Python with `venv`, an OpenAI API key, and a modern browser. Microphone access works on `localhost` or HTTPS.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `.env` in the project root:

```dotenv
OPENAI_API_KEY=your_key_here
VAST_MODEL=gpt-4o-mini
VAST_REALTIME_MODEL=gpt-realtime
VAST_REALTIME_VOICE=marin
VAST_VOICE_ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
```

`VAST_MODEL` is the application agent model. `VAST_REALTIME_MODEL` is used only for voice transcription/playback.

### Optional seed data

The server creates `data/vast.db` automatically. To load clinic/patient/booking seed data, place these files in `data/`:

```text
clinics.csv
patients.csv
bookings.csv
```

Then run:

```bash
python -m app.ingest
```

## 2. Run

```bash
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Open `http://127.0.0.1:8000`.

Use **New chat** to start a session. Type normally, or press **Start voice**, speak, and pause. When buttons are visible, clicking a button or saying an equivalent intent uses the same backend action. Slot buttons remain visual; voice summarizes the choices instead of reading every button.

Useful checks:

```bash
curl http://127.0.0.1:8000/health
VAST_TEST_STUB_OPENAI=1 python -m pytest -q
```

## 3. Main runtime files

```text
app/main.py                       FastAPI startup/routes
app/chat.py                       /api/chat, /api/reset, /api/config
app/voice.py                      Realtime WebRTC session creation
app/static/index.html             Browser chat + voice orchestration
app/static/voice.js               STT/TTS WebRTC lifecycle
services/chat.py                  One serialized application turn
agents/nextdim/agent.py           Conversation state machine entry point
agents/nextdim/action_intent.py   Natural language -> visible canonical action
agents/nextdim/steps/             State-specific conversation handlers
services/                         Validation/business services
repositories/                     SQLite persistence
```

See `documents/architecture.md` for the exact flow and `GUARDRAILS_AND_LIMITATIONS.md` for enforced constraints and known limits.

## 4. Important deployment notes

- Sessions are in memory and disappear on restart.
- Run a single application worker unless session storage/locking is redesigned for multi-process use.
- Chat confirmation is not identity authentication; do not expose real patient records without a separate authenticated/authorized boundary.
- Voice origin checks are not authentication.
- `gpt-realtime` speech is generative; the visible text reply is authoritative.