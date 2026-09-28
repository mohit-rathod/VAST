# Version 0.2 limitations and pre-existing constraints

## Explicit boundaries

- **Single-process demo authentication:** session storage, OTP challenges and send
  limits are in memory. Restarting loses sessions; multiple workers do not share
  them. The original 200-session clear-all capacity policy remains. Do not treat
  this as a production identity platform, distributed rate limiter, or compliance
  certification. Add durable authenticated sessions, access controls, audit
  policy, expiration and distributed abuse protections before production use.
- **Email proof only:** existing-account access/contact recovery proves access to
  the prior mailbox. It does not verify phone reachability or ownership of the
  newly proposed contact details. New registration follows the existing creation
  flow without verifying the new email. Lost access to the old mailbox needs a
  separate staff-assisted process. Shared/ambiguous contacts are not auto-merged.
- **Structural phone validation:** no full country-numbering-plan database is
  included. An explicit international prefix is required outside US/Canada
  national input. Some structurally valid values can still be unallocated.
  Incomplete legacy numbers are quarantined, not repaired by guessing.
- **English calendar grammar:** common relative/absolute dates and periods are
  deterministic. Ambiguous or unsupported forms require clarification, not a
  claim to understand every natural-language date. Multiple clinics/timezones
  beyond the supplied New York ZIP map need dedicated cross-zone range tests.
- **Booking window and schedules:** opening hours remain 09:00-17:00 every day in
  the rolling window. There is no holiday, practitioner roster or capacity
  integration. The one-hour booking is one record under the authenticated patient,
  not two identities or a family/dependent booking system.
- **Cancelled-start uniqueness:** the existing unconditional
  `UNIQUE(clinic_id, slot_date, start_time)` constraint can block reusing a cancelled
  appointment's exact start even though cancelled appointments are not busy.
  The application reports failure and does not falsely confirm a booking. A
  separate schema/cancellation lifecycle change is needed to resolve this.
- **Trusted local tools:** Python tool functions are not public authenticated
  endpoints. Authorization is enforced in the chat flow/history service. Do not
  expose arbitrary patient IDs, `verified=True`, or low-level update functions
  directly through another unprotected API.
- **Other inherited behavior:** supported ZIPs/geocoding are sample-only; unknown
  ZIPs do not produce invented coordinates. Clinical interpretation still uses
  the original model workflow. It has not been assessed for clinical safety.
  The model sees free-text input; extracted phones are normalized afterward.
- **Storage migration:** patients/clinics/bookings in the supplied schema are
  preserved. Custom patient-table columns, triggers or indexes were not provided
  and must be assessed before the table rebuild. Back up the live database first.
- **External integrations:** automated tests use scripted model output and a fake
  email sender. A mocked SMTP test checks message construction and STARTTLS/auth
  ordering, not real delivery. Live OpenAI/SMTP and the original exact dependency
  pins were not validated in this sandbox.

## Prior defects addressed in this release

The missing `NOTE` import on structured-output retries, option-number indexing,
explicit-time ranking, ZIP-coordinate refresh, unknown-ZIP registration failure,
and stale session ID reuse have been fixed and tested because they intersect the
new flows. The old regression snapshot is kept only as historical evidence;
`tests/fixtures/v0_2.json` is the current expected snapshot.