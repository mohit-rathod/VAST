# VAST / NextDim architecture — v0.2.3

## Runtime flow

```mermaid
flowchart TD
    A[Browser: index.html] -->|New chat| B[POST /api/reset]
    B --> C[ChatService.reset]
    C --> D[In-memory session: NextDimAgent]
    D --> A

    A -->|Typed text / button| E[submitMessage]
    A -->|Microphone| F[voice.js WebRTC]
    F --> G[POST /api/voice/session]
    G --> H[OpenAI gpt-realtime]
    H -->|Transcript only| E

    E -->|POST /api/chat + session_id\nX-Resolve-Actions: 1| I[app/chat.py]
    I --> J[ChatService.turn]
    J -->|same-session RLock| K[NextDimAgent.handle]

    K --> L{Match a current action?}
    L -->|Exact button/label| M[Canonical action message]
    L -->|Natural language| N[action_intent.py LLM classifier]
    N -->|one clear current action| M
    N -->|no/ambiguous match| O[Original user message]

    M --> P[controls + current step handler]
    O --> P
    P --> Q[LLM extraction/classification where needed]
    P --> R[Deterministic services]
    R --> S[SQLite repositories]
    S --> P
    Q --> P

    P --> T[reply + state + actions + trace]
    T --> J --> I --> A

    A -->|display full reply| U[UI]
    A -->|speech-safe reply| V[voice.js speech queue]
    V --> H
    H -->|audio only| W[Speakers]
```

## Exact code path

1. `app/main.py` initializes SQLite and registers chat + voice routers.
2. `POST /api/reset` -> `services/chat.py:ChatService.reset()` -> `app/sessions.py:new_session()` -> `NextDimAgent.start()`.
3. Typed text, button messages, and voice transcripts all reach `submitMessage()` in `app/static/index.html`.
4. Voice uses `app/voice.py` only to establish WebRTC with `gpt-realtime`; Realtime does not own application decisions or tools.
5. Browser turns call `POST /api/chat` with `X-Resolve-Actions: 1`.
6. `ChatService.turn()` finds the session and holds the agent's re-entrant turn lock for the full turn.
7. `NextDimAgent.handle()` optionally calls `agents/nextdim/action_intent.py`:
   - exact current button payload/label -> deterministic canonical action;
   - clear paraphrase -> LLM may select only one currently visible canonical action;
   - ambiguous/new information -> original message continues unchanged.
8. `agents/nextdim/controls.py` handles lifecycle commands; otherwise `agents/nextdim/steps/HANDLERS` executes the current state.
9. Step handlers use structured LLM calls only for language interpretation and use deterministic services/tools for contacts, dates, clinics, availability, history, and booking.
10. Repositories persist patients/bookings in SQLite. Booking reservation is transaction-protected and rechecks slot occupancy before insert.
11. `/api/chat` returns `reply`, `step`, `actions`, trace events, booking/history data, and the same `session_id`.
12. The browser displays the full reply. TTS speaks a speech-safe version: normal answers are preserved; slot grids/buttons are summarized instead of narrated. Replay never calls `/api/chat`.

## Conversation state flow

```mermaid
flowchart LR
    A[details] --> B[registry]
    B -->|new patient| C[complaint]
    B -->|returning + confirmed| M[menu]
    B -->|contact mismatch| R[recovery]
    R --> RC[contact_confirm]
    RC --> M
    M -->|book| C
    C --> D[clinic]
    D --> E[slots]
    E --> F[book]
    F --> G[done]
    M -->|history| M
    A -. end request .-> X[end_confirm]
    B -. end request .-> X
    C -. end request .-> X
    D -. end request .-> X
    E -. end request .-> X
    F -. end request .-> X
    M -. end request .-> X
    X -->|yes| G
    X -->|no| Y[previous state]
```

Email codes are not part of this flow. `flow.verified` means **confirmed in the current chat**, not authenticated identity.
