# Version 0.2.1 tests

Run from the repository root in the working runtime environment:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

All model replies and verification delivery are test doubles. Databases are
created under pytest temporary directories; tests do not alter the supplied
`data/vast.db`. No live API key or SMTP credentials are needed for tests.

For an offline environment where the SDK cannot be imported:

```bash
VAST_TEST_STUB_OPENAI=1 python -m pytest -q
```

PowerShell equivalent:

```powershell
$env:VAST_TEST_STUB_OPENAI = "1"
python -m pytest -q
Remove-Item Env:VAST_TEST_STUB_OPENAI
```

The import stub is installed only by test tooling, and rejects live client
construction. The optional browser check uses the same explicit offline switch. Deterministic OTP values exist only in fixtures. Production code never uses these test values. The explicit trusted-demo
setting `VAST_REQUIRE_EMAIL_VERIFICATION=false` is not email ownership verification. Scripted tests do
not prove compatibility with the real SDK, SMTP server or model responses.

## Current coverage areas

`test_requested_features.py` covers canonicalization at model/service/SQL
boundaries; incomplete legacy data; exact/partial/ambiguous identities; email
challenges, expiry, attempts and replay; both-contact recovery with confirmation
and stale-write protection; day/week/weekend/range resolution; timezone/DST and
year boundaries; invalid/ambiguous dates/times; fixed/rolling availability;
expired selections; exact-time ranking; one-hour overlap/closing/race behavior;
end-confirm/decline/replay; menu interruption/resume; and history isolation.

`test_api.py` covers request/response schemas, server-driven actions, missing-key
end controls, authenticated history, automatic booking closure, errors and
session replacement. Existing service/repository and agent tests were updated
where the requested behavior intentionally differs from v0.1. There is no claim
that the new suite should still pass against the old application.

`tests/fixtures/v0_2_1.json` is the current checked-in regression snapshot of replies,
events, model payloads, API/domain schemas and ranking/availability results.
`baseline.json` and `v0_2.json` remain historical artifacts, not active expected
results. Never set `VAST_WRITE_BASELINE=1` during normal verification; it would
regenerate the expectation instead of independently checking it.

`test_chat_usability.py` adds malformed-contact feedback and partial-correction
coverage, protects the source from model format repair, checks LLM confirmations
against the fixed selection, and covers decline/unclear/failure/double-submit,
state-aware actions, noon/DST/window boundaries and time-filter preservation.
The updated suite has 361 test cases (265 before this patch, 96 additional cases).

## Optional browser check

Install Playwright separately in a development environment; it is not a runtime
or mandatory pytest dependency. Use its installed Chromium, or an explicit local
browser path:

```bash
python -m pip install playwright
python -m playwright install chromium
VAST_TEST_STUB_OPENAI=1 python -m scripts.verify_chat_ui
# Alternatively add --chromium /path/to/chromium
```

This runs the real agent with a temporary database, a scripted model and a browser
fetch bridge. No HTTP networking, live LLM call or SMTP is performed. It exercises
desktop/mobile layout, slot selection, natural confirmation, closure/reset,
confirmation buttons, idle-noon expiry and midnight label/payload consistency.
Screenshots and results default to the gitignored `artifacts/ui-v0.2.1` directory.
The normal API tests independently exercise FastAPI request/response behavior.

## Coverage command

```bash
VAST_TEST_STUB_OPENAI=1 python -m coverage run --branch \
  --source=app,agents,domain,repositories,services,tools -m pytest -q
python -m coverage report -m
```

See `documents/verification-v0.2.1.json` for the actual run counts/versions and
`documents/coverage-v0.2.1.txt` for file-level execution coverage. Coverage is not a
proof of complete correctness, security or all possible language variations.
The prior parity scripts are preserved for investigation; differences against
v0.1 are expected in this behavior-changing release.