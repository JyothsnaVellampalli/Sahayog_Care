# Phase 3 - Data ingestion - Progress

Status: Complete (confirmed by the project owner on 2026-10-29).

### Done When - checklist

- [x] Reflect the new symptom catalogue in the application.
- [x] Complete database visit-data cleanup and appointment schema updates.

### Delivered

- Intake uses `backend/app/book_appointment/data/symptoms_2.json` for symptom
  labels, specialty and severity metadata across the frontend and backend.
  Supported specialties are Cardiology, Orthopedics, Dermatology and
  Gastroenterology.
- Symptom selection is optional: patients can submit a natural-language
  description alone. Empty submissions and unknown symptom IDs are rejected.
- Catalogue emergency/severe selections set a severity floor; mild and moderate
  map to Normal in the existing routing. The combined Jev call interprets
  multilingual text and specialty, with no forced specialty for unsupported cases.
- `appointments.symptom_text` replaces `history` for the de-identified patient
  description. Nullable `specialty_id` references `specialties` and preserves the
  assessed specialty through booking and emergency assignment.
- Removed appointment fields: `legacy_consultation_id`, `allergies` and `vitals`.
  Consultation storage uses the shared appointment ID.
- Added `backend/database/phase_3_cleanup.sql` to reset appointments, emergency
  intakes and legacy consultation rows and release booked slots. Patient and
  doctor records, signatures, schedules and blocked slots are preserved.
- Added `backend/database/phase_3.sql` for the schema changes, supported specialty
  names and updated atomic booking RPC. Browser drafts use a new versioned key.

### Implementation and verification references

See [Phase 3 implementation and rollout](../Phase3.md) for migration order,
storage retention behavior, coordinated deployment and smoke checks. This phase
supersedes Phase 2's historical `history` and `legacy_consultation_id` contracts.

Regression coverage is in `backend/tests/test_phase3.py` and the related booking,
patient and consultation suites; frontend flow coverage is in
`frontend/tests/patient-flows.spec.js`. Tests use stubbed models and database
clients, so they do not establish clinical accuracy or live migration execution.
Completion is recorded from the project owner's confirmation; no migrations or
application tests were rerun for this documentation-only update.
