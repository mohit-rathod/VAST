# VAST architecture - v0.2.0

The current behavior and migration specification is `UPDATE_V0_2.md`. The earlier
behavior-preserving refactor report is retained as a historical document only.

```text
Browser (HTML/JS, server-driven actions)
    -> FastAPI routes + Pydantic transport models
        -> ChatService (session lookup, serialized turn/result capture)
            -> SessionStore / NextDimAgent
                -> Flow and global controls
                -> Detail / registry / recovery / verification / menu steps
                -> Complaint / deterministic scheduling / booking steps
                    -> Tool composition roots
                        -> PatientService / IdentityService
                        -> AvailabilityService / BookingService
                        -> HistoryService / ClinicService
                            -> Small domain repository protocols
                                -> SQLite adapters
                                    -> connection + schema/migration
                -> VerificationService -> CodeSender -> SMTPCodeSender
                -> DateResolver / duration helpers / canonical phone rules
                -> LLM structured extraction (not date selection)
```

## State paths

```text
New record: details -> registry/address confirmation -> complaint -> clinic
Returning: details -> verify email -> registry confirmation -> menu
Mismatch:  details -> recovery (collect BOTH contacts) -> verify prior email
                   -> contact confirmation -> atomic update -> registry -> menu
Ambiguous: details -> recovery_id (old email) -> recovery -> verify -> confirm
Booking:   menu -> complaint -> clinic/date preferences -> slots -> book -> done
History:   verified state -> menu/history/directory -> continue or new appointment
Any active state: end request -> end_confirm -> done (yes) / previous state (no)
```

Booking failure returns to explicit selection; success goes directly to `done`.
A terminal agent never invokes the model or creates a second booking. History
selection uses the session's verified patient ID; the browser supplies no patient
ID or verification flag. The same session lock covers callback binding and state
capture as well as agent execution. The database transaction separately protects
shared appointment intervals across sessions.

## Persistence

`clinics`, `patients`, and `bookings` retain existing identities and booking rows.
Patient phones become nullable to safely represent legacy numbers that cannot be
normalized; `patient_phone_issues` stores their original values/reasons for repair.
Booking `start_time` and `end_time` express either a 30- or 60-minute interval.
History is read with a patient-scoped join over all clinics and no status/date
filter. Existing cancelled-start uniqueness is documented in `KNOWN_ISSUES.md`.

## External dependencies

OpenAI still performs structured extraction/clinical classification through the
existing helper. SMTP supplies one-use account verification. The supplied ZIP/CSV
geocoder remains New York-only. Python standard-library timezone/date and SMTP
facilities are used; runtime dependency pins were not modified.