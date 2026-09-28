# Guardrails and limitations — v0.2.3

This file lists safeguards and constraints explicitly enforced by the current codebase, followed by important limitations that remain.

## Guardrails enforced in code

| Area | Enforced behavior | Main code |
|---|---|---|
| Chat input | A chat message must be 1–2,000 characters. | `app/schemas.py`, frontend `index.html` |
| Session isolation | One `NextDimAgent` is kept per session ID; a re-entrant lock serializes turns sharing that session. | `app/sessions.py`, `services/chat.py`, `agents/nextdim/agent.py` |
| Session growth | In-memory sessions are capped at 200; hitting the cap clears the session map before creating the next session. | `app/sessions.py` |
| LLM output validation | Application LLM calls must parse into the requested Pydantic model. One retry is allowed; unusable JSON cannot advance the turn. | `agents/nextdim/llm.py` |
| Sensitive traces | Intake/contact extraction payloads and model outputs are redacted from model trace events. | `agents/nextdim/llm.py` |
| Visible-action resolution | Natural language may resolve only to an action currently offered by the state machine. The classifier cannot invent/rewrite a canonical action. | `agents/nextdim/action_intent.py` |
| Ambiguous action speech | Ambiguous intent, or new factual data such as a changed contact/symptom/date/time, falls through to normal conversation instead of forcing a button action. | `agents/nextdim/action_intent.py` |
| End-chat intent | A generic negative response is not mapped to `End chat`; explicit end intent is required and ending is separately confirmed. | `agents/nextdim/action_intent.py`, `agents/nextdim/controls.py` |
| Deterministic button clicks | Exact action payloads/labels bypass semantic LLM matching and use their canonical message directly. | `agents/nextdim/action_intent.py` |
| Contact confirmation | Matching a patient record does not unlock account/history actions by itself; explicit in-chat confirmation is required. | `agents/nextdim/steps/account.py`, `registry.py` |
| Email verification | Email OTP/code verification is explicitly disabled; `VAST_REQUIRE_EMAIL_VERIFICATION` is ignored. | `app/config.py` |
| Contact update safety | Recovery collects both contacts, confirms them, normalizes them, checks duplicates, and uses a stored contact fingerprint to reject stale/concurrent updates. | `agents/nextdim/steps/account.py`, patient services/repository |
| Email syntax | Length/structure are validated; quoted local parts, IP-literal domains, and Unicode mailbox syntax are rejected rather than silently rewritten. | `domain/email.py` |
| Phone handling | Invalid/ambiguous numbers, letters/extensions, malformed parentheses, and guessed country context are rejected. Chat intake requires exactly 10 national digits; canonical storage uses E.164. | `domain/phone.py`, `services/contact_input.py` |
| Legacy phone data | Invalid legacy phone values are quarantined in `patient_phone_issues` and removed from live matching/display instead of being guessed. | `app/db.py` |
| Date/time interpretation | Calendar resolution is deterministic; the LLM does not choose dates. Bounded ranges are not silently treated as exact start times. | `services/date_resolver.py`, scheduling step |
| Complaint loop | Complaint clarification is bounded to 3 rounds so the conversation cannot remain in an endless clarification loop. | `agents/nextdim/conversation.py` |
| Booking race safety | Reservation acquires a booking lock, starts `BEGIN IMMEDIATE`, rechecks overlap, and relies on a uniqueness constraint before commit. | `repositories/bookings.py`, `app/db.py` |
| No automatic chat retry | The browser does not automatically retry `/api/chat`, preventing duplicate booking/contact side effects. | `app/static/index.html` |
| Voice origin | `/api/voice/session` accepts only an exact configured browser origin. | `app/voice.py` |
| Voice session/SDP validation | Voice requires an existing chat session; session ID/SDP lengths are bounded and SDP must begin with `v=0`. | `app/voice.py` |
| Server-side OpenAI key | The API key is used only by the server during WebRTC negotiation; it is not returned to the browser. | `app/voice.py` |
| Realtime authority | Realtime has no tools, `tool_choice` is `none`, automatic responses are disabled, and it is instructed to transcribe/read rather than make application decisions. | `app/voice.py` |
| Voice overlap | Microphone input is paused during agent work and TTS; late/overlapping audio items are discarded rather than becoming another agent turn. | `app/static/voice.js` |
| Voice duration | Idle listening stops after 3 minutes; one spoken input turn is bounded to 45 seconds. | `app/static/voice.js` |
| Voice transcript size | STT output over 2,000 characters is rejected before chat submission. | `app/static/voice.js` |
| TTS chunking | Speech text is split into ordered chunks of at most 600 characters; only one Realtime response is active at a time. | `app/static/voice.js` |
| Slot narration | Slot/action buttons are not read one by one; the visible detailed list remains on screen while TTS gives a concise conversational summary. | `app/static/index.html` |
| Replay side effects | Replay calls TTS only and never calls `/api/chat`, so it cannot repeat a booking/contact update. | `app/static/index.html` |
| Voice response bounds | Realtime negotiation uses a 25-second upstream timeout and rejects SDP answers larger than 256 KiB or with an invalid prefix. | `app/voice.py` |

## Current limitations

1. **Chat confirmation is not authentication.** Knowing/matching contact details plus confirming them in chat does not prove identity. Real patient data requires an external authenticated and authorized account boundary.
2. **Voice origin checking is not authentication.** It only limits which browser origins can negotiate voice.
3. **Sessions are process-local memory.** Restarting the server loses conversations. The 200-session cap clears all active in-memory sessions when reached.
4. **Use one application worker in the current design.** Multiple workers would have separate session maps and process-local locks unless shared session/locking infrastructure is added.
5. **No built-in per-user rate, concurrency, or spending quota exists.** Add those controls before public deployment.
6. **`gpt-realtime` speech is generative.** Complete text is queued, but exact word-for-word pronunciation is not guaranteed; displayed text is authoritative.
7. **STT can mishear speech.** The transcript is treated as user input after the configured checks; critical details should still be visibly reviewed/confirmed.
8. **Semantic action matching is probabilistic.** It is constrained to current actions and can return no match, but the classifier can still misunderstand a paraphrase.
9. **Email validation checks syntax only.** It does not prove mailbox existence, reachability, or ownership.
10. **Phone validation checks structure only.** It does not prove number allocation, reachability, or ownership.
11. **The included voice flow is turn-based.** The microphone is intentionally muted while the agent works/speaks; full duplex interruption/barge-in is disabled.
12. **SQLite is the persistence layer.** It is suitable for this deployment shape, but the current architecture is not a distributed transaction/session design.
13. **Seed CSVs are not bundled in this source package.** Without clinic data, the application can start but cannot provide meaningful appointment inventory until data is loaded.
14. **Email-code modules may remain for compatibility/tests.** They are not invoked by the active conversation path and should not be interpreted as enabled email verification.
