# VAST / NextDim - version 0.2.1

> **Optional chat-only contact hotfix:** To collect/update email and phone without
> sending verification emails, set `VAST_REQUIRE_EMAIL_VERIFICATION=false` in
> your existing `.env` and restart the backend. The default remains email
> verification when the flag is absent. This is a trusted-demo mode, not proof
> of account ownership. See `documents/CHAT_ONLY_CONTACT_HOTFIX.md`.

A Python/FastAPI clinic appointment chatbot with SQLite persistence, deterministic
appointment selection and a server-driven browser interface. This release builds
on the previous no-email release. It adds explicit contact-format feedback,
LLM-assisted booking confirmation, and context-aware confirmation/date buttons.
The earlier account, duration, lifecycle and history features remain available.

This is a behavior-changing release, not another parity-only refactor. The
original runtime dependency pins and supplied database/CSV files are unchanged.
Read `documents/UPDATE_V0_2_1.md` for this update. `documents/UPDATE_V0_2.md`
describes the earlier migration; this update introduces no new database migration.

## Setup

Use the existing working Python environment from the previous release. For a new
environment, install `requirements.txt` and, for tests, `requirements-dev.txt`.
The supplied pins have not been independently revalidated against a package index.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

On Windows, activate with `.venv\Scripts\Activate.ps1` and copy the example with
`Copy-Item .env.example .env`. When upgrading, keep the existing `.env` and add the
new settings rather than replacing existing credentials.

Configure `OPENAI_API_KEY`. Keep `VAST_REQUIRE_EMAIL_VERIFICATION=false` to
collect and update contacts entirely in chat without sending email. The SMTP
settings below are needed only when restoring verification with `true`. If the
flag is absent, verification remains enabled. Contact-only mode does not prove
account ownership and must not be exposed publicly with real patient data.

```dotenv
VAST_REQUIRE_EMAIL_VERIFICATION=false
VAST_PHONE_REGION=US
VAST_BOOKING_DAYS=14
VAST_FIRST_DAY=
VAST_SMTP_HOST=your-starttls-smtp-host
VAST_SMTP_PORT=587
VAST_SMTP_FROM=your-verified-sender-address
VAST_SMTP_USERNAME=your-smtp-username
VAST_SMTP_PASSWORD=your-smtp-password
```

When verification is enabled, the SMTP adapter does not support implicit-TLS port 465. Configure a STARTTLS
endpoint. New proposed contacts are confirmed by the user; email ownership is verified
using the **previous email**, not the proposed replacement email or phone.

Before first startup on an existing database, take a SQLite backup and audit the
phone data as explained below. Then start the application:

```bash
python -m uvicorn app.main:app --reload --port 8000
```

The UI is at `http://127.0.0.1:8000`. Existing routes remain: `GET /`, `GET /health`,
`GET /api/config`, `POST /api/reset`, and `POST /api/chat`.

## Back up and migrate existing data

Do not overwrite your current `data/vast.db` with the ZIP's supplied snapshot.
Stop the application during deployment. Make a consistent SQLite backup before
startup performs the migration. For example, from the repository root:

```python
from contextlib import closing
from pathlib import Path
import sqlite3

source = Path("data/vast.db").resolve()
target = Path("data/vast-before-v0.2.db")
if not source.is_file():
    raise FileNotFoundError(source)
# Exclusive creation prevents accidentally overwriting an earlier backup.
with target.open("xb"):
    pass
try:
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
except Exception:
    target.unlink(missing_ok=True)
    raise
```

Run the read-only preflight:

```bash
python -m scripts.audit_phones
```

The supplied snapshot contains 104 patients: 3 valid, normalizable phone numbers
and 101 incomplete numbers missing area-code digits. Those 101 values cannot be
converted safely. Startup preserves their original values/reasons in
`patient_phone_issues`, sets the active `patients.phone` value to NULL, and requires
contact recovery under the configured verification policy. It does not invent digits. The migration normalizes
valid phones, retains all other patient fields and bookings, preserves foreign
keys, and is idempotent. A corrected phone removes its repair entry.

The CSV files have not been edited either. The optional demo importer applies the
same normalization/quarantine rules. **Do not run `app.ingest`, `make reingest`,
`make reset` or `make clean` against an existing installation as part of this
upgrade:** these are demo data replacement/deletion commands, not migrations.
The included SQL migration is tested against the supplied schema; custom schema
extensions require review before running the table rebuild.

## Patient and contact flow

1. Collect name, email and phone without format instructions in the greeting.
   Validate entered contacts locally before lookup. Incorrect values receive the
   entered value and the required format; other valid intake fields are retained.
2. With verification disabled, an exact contact match reads the record back for
   confirmation. With verification enabled, the existing email-code step runs first.
3. A partial match collects both updated contacts, reads them back, and requires
   explicit confirmation before an atomic update. Invalid corrections block saving
   an earlier proposal. Email verification is added only when enabled.
4. Ambiguous/shared contacts do not choose an account. `recover account` asks for
   the email on file. Two entirely changed contacts cannot identify an account by name.
5. Returning users can view all their bookings, book an appointment, view clinics,
   or end the chat.

Chat phone input must contain exactly **10 national digits**. Spaces, parentheses
and hyphens are accepted, but country prefixes, extensions and wrong digit counts
are rejected with guidance. The supplied US/Canada configuration converts
`(212) 555-0100` into `+12125550100` before lookup or persistence. The storage/tool
normalizer still preserves existing international records; the new ten-digit
chat-entry rule does not rewrite the database. Non-US/Canada chat entry requires
an explicit country-input policy change, not guessed digits or a guessed country.

Emails use ordinary `name@example.com` syntax, including plus aliases and
subdomains. Missing/duplicate @, whitespace, invalid dots and malformed domain
labels are rejected. Quoted local parts, IP literals and internationalized
addresses are not supported. Validation does not prove mailbox or phone ownership,
reachability, or assignment; no DNS lookup or SMS verification was added.

When email verification is enabled, codes expire after ten minutes, allow five
attempts, and are single-use. Resends have a 60-second minimum interval and a
five-per-hour limit per destination within this process. An inaccessible existing
mailbox requires clinic-assisted recovery.

## Confirmation and date buttons

Address checks, patient details, complaint restatements and contact updates have
confirm/edit buttons. Displayed appointments have selection buttons; the booking
read-back offers **Confirm booking**, **Choose another slot** and **Change date**.
Choosing a slot does not book it. Clicking Confirm booking uses the same guarded
booking path as a typed confirmation, without an LLM round trip.

Natural replies such as `I confirm this slot` are classified against the selected
appointment. Explicit changes are routed to scheduling. Unclear responses or model
failures keep the selected appointment unbooked, instead of re-running the search.
Availability and the final atomic write remain application responsibilities.

During scheduling, up to seven allowed dates are displayed with weekdays and ISO
dates. Before 12:00 clinic-local time, Today is eligible; at/after 12:00 the shortcuts
start from tomorrow. Dates outside `VAST_FIRST_DAY` / `VAST_BOOKING_DAYS` are excluded.
Idle-browser buttons expire at noon and relative labels update at midnight without
changing their absolute date payload. These are shortcuts, not guaranteed openings.
Explicitly typed same-day requests still use the existing future-slot availability
rules; this is not a new prohibition on all afternoon same-day bookings.

Morning, Afternoon and Any time buttons retain the selected date range. Long chats
scroll the conversation pane to the latest reply rather than scrolling the page body.

## Dates, times and duration

Appointment dates are resolved by application code, not by the language model.
The supplied New York dataset uses `America/New_York`, including daylight-saving
transitions. Relative dates follow that clock, not the browser's timezone or UTC.

Supported examples include `today`, `tomorrow morning`, `day after tomorrow`,
`in two days`, `Friday`, `next Friday`, `this week`, `next weekend`,
`Wednesday through Friday`, `2026-10-02`, and `2 October 2026`.

Weeks run Monday through Sunday. A bare weekday is its next occurrence, including
today; `this Friday` means the current calendar week's Friday; `next Friday`
means next calendar week's Friday. `this week` searches the remaining days.
Explicit dates without a year use the current clinic-local year; past dates are
not silently pushed into the following year. Numeric slash dates, conflicting
date/weekday combinations, unsupported before/after boundaries and ambiguous
clock times ask for clarification. English is the supported parsing language.

The default booking window is rolling today plus the next 13 days. Set
`VAST_BOOKING_DAYS` to change its length. Leave `VAST_FIRST_DAY` empty for normal
operation; a fixed demo start is optional. Existing opening hours remain 09:00 to
17:00, with 30-minute grid increments. There is no holiday/provider-roster engine.
Same-day slots that have passed are omitted and rejected again on confirmation.

The chat never silently widens a requested date range. When only part of a range
fits the available window, the displayed search range states the actual dates.
An explicit time is used for ranking; nearby times can be offered, but their exact
start/end are displayed and require selection and confirmation. Slot lists,
confirmation and booking receipts contain the weekday, ISO date, start/end and
timezone. Example: `Friday 2026-10-02, 10:00 to 11:00 America/New_York time`.

The default duration is 30 minutes. A request for two people produces:

> I am trying to find a slot for 1 hour.

It reserves one continuous 60-minute interval as **one booking record** for the
verified patient, rather than creating a second patient or dependent appointment.
A request exceeding one hour is refused. Both halves of a one-hour interval must
be free, fit before closing, and pass an interval-overlap recheck in the write
transaction. Headcount is not proactively requested or discussed by the replies.

## Ending and restarting

An **End chat** button is available throughout active conversation stages. Text
such as `end chat`, `please end the chat`, `quit` and `bye` uses the same flow.
Before an appointment is created, the bot asks once whether to end without
booking: Yes closes; No restores the prior step. Ending a chat never cancels an
existing appointment.

A successful booking returns its receipt and `done=true` immediately. No second
end confirmation is required. Input/actions are disabled, replayed confirmations
cannot create another booking, and **New chat** creates a fresh session. Failed
bookings keep the flow open for another explicit choice.

## Booking history and clinics

A returning user verifies their account before personal history is returned.
**View all my bookings** retrieves that patient's bookings across all clinics,
including past, future, completed and cancelled records, with clinic details,
weekday/date/timezone and status. **View all clinics** is a separate complete
clinic directory. Patient identity comes from the verified session, not a patient
ID supplied in chat. This is history display, not appointment cancellation.

The chat response retains its original fields and adds:

```json
{
  "actions": [{"label": "End chat", "message": "end chat"}],
  "bookings": null
}
```

`bookings` becomes the verified patient's list after a history request. The
singular `booking` field still describes a booking created in this chat.

## Code boundaries

```text
HTTP/UI -> ChatService -> NextDimAgent / flow controls / step handlers
                               |
                               +-> domain phone/models and deterministic dates/duration
                               +-> tools -> services -> repository protocols
                               |                       -> SQLite adapters
                               +-> VerificationService -> CodeSender -> SMTPCodeSender
```

`domain/phone.py` owns canonicalization. `services/identity.py` owns match
classification; `services/verification.py` owns challenges; `steps/account.py`
owns account conversation transitions. `services/date_resolver.py` and
`services/duration.py` own deterministic interpretation. SQL remains in
`repositories/`, including the scoped history query and interval-overlap check.
Pure helpers stay functions; classes are used for dependencies and stateful rules.

See `documents/UPDATE_V0_2_1.md` for the current change map and limitations.
New boundaries: `services/contact_input.py` validates raw contacts;
`agents/nextdim/booking_intent.py` interprets selected-slot consent;
`services/date_shortcuts.py` owns the noon/range policy;
`agents/nextdim/actions.py` builds actions; `app/static/chat-actions.js` renders them.

## Validation

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Tests use temporary databases, scripted model replies, frozen clocks and an
injected test-only email sender. They do not contact OpenAI or SMTP. If the SDK is
not importable in an offline environment, use:

```bash
VAST_TEST_STUB_OPENAI=1 python -m pytest -q
```

That switch installs an import stub only inside pytest. It is not a production
OTP or authentication bypass. See `tests/README.md` and the measured reports in
`documents/`. Live SDK/SMTP integration, the supplied dependency pins, and a
production authentication deployment still require validation in your environment.