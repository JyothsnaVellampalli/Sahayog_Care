# Phase 3 - Data ingestion - Progress

Status: Complete (confirmed by the project owner on 2026-10-29).

### Done When - checklist

- [x] Reflect the new symptom catalogue in the application.
- [x] Complete database visit-data cleanup and appointment schema updates.

### Delivered - symptom catalogue

- The application reads `backend/app/book_appointment/data/symptoms_2.json`
  directly: 132 symptoms covering Cardiology, Orthopedics, Dermatology and
  Gastroenterology. The catalogue validates unique IDs/codes, severity, weight
  and specialty at load time.
- Served through `/api/symptoms`; no separate symptom-table ingestion is
  needed. The old `symptoms.json` and `symptom_categories.json` are retained
  only as historical files and are no longer read by the intake flow.
- The catalogue is cached per process, so the backend must be restarted after
  editing it.

### Delivered - intake behavior

- Symptom selection is optional: a patient can submit a natural-language
  description alone. Empty intake and unknown symptom IDs return `422`.
  Duration is optional. Severity shown in the form comes from the catalogue;
  the backend resolves metadata itself rather than trusting client values.
- Catalogue `emergency` maps to Emergency, `severe` maps to Severe, and
  `mild`/`moderate` map to Normal for the existing three-level routing. The
  original catalogue metadata (the finer-grained levels) remains available
  even though routing collapses to three tiers.
- Model interpretation may escalate a case based on context or free text, but
  it can never downgrade it: an explicit emergency or severe symptom selection
  cannot be reduced by model scores or patient-reported intensity.
- An explicit emergency selection still takes the emergency path even if the
  classification model is unavailable. Other model failures (non-emergency
  cases where the model call fails) offer no slots rather than guessing.
- One combined Jev call still handles multilingual free text and specialty
  together. Unsupported conditions can return no specialty instead of being
  forced into one of the four supported specialties. Insufficient information
  also offers no slots.
- Specialty choices are filtered to the existing DB codes `CARD`, `ORTH`,
  `DERM`, `GAST`. Other specialty and doctor records in the database remain
  intact (not deleted), they are simply not offered. Location-based doctor
  filtering from Phase 1.5 remains unchanged.
- Browser intake drafts use a new versioned storage key so that reused
  symptom IDs under the new catalogue cannot silently restore stale selections
  from before the switch. Existing open browser tabs must reload after the
  release ships, since their in-memory draft key is stale.

### Delivered - appointment schema

- `appointments.symptom_text` replaces `history` throughout both portals and
  the booking RPC. The field name previously implied clinical/medical history;
  it actually stores the de-identified patient-written description, so the
  rename corrects that mismatch.
- Added a nullable `appointments.specialty_id` referencing `specialties.id`.
  The specialty identified by the first symptom assessment travels with
  booking and is persisted when the appointment is created. Intake alone
  (before a slot is chosen) does not create an appointment row.
- Emergency intake retains its own assessment and specialty; manual
  doctor/slot assignment for a pending emergency copies that specialty onto
  the appointment.
- Patient appointment views join the appointment's stored specialty rather
  than inferring it from the doctor's *current* specialty (which could have
  changed since booking). Normal (non-emergency) booking validates that the
  chosen doctor's specialty agrees with the booked specialty.
- Removed appointment fields that were irrelevant to the new data model:
  `legacy_consultation_id`, `allergies`, `vitals`.
- Consultation, transcript, SOAP and signed-snapshot storage continue to use
  the shared appointment ID as the key; this did not change in Phase 3.
  Clinical information discussed during the consultation itself can still
  appear in the SOAP note even though it is no longer captured via the removed
  `allergies`/`vitals` intake fields.

### Database rollout

This was executed as a coordinated maintenance-window switch, not a rolling
migration: old and new application versions use different column/RPC
contracts and cannot run against the same database simultaneously. The SQL
files were provided for the operator to run manually; they are not
auto-applied by application startup.

Rollout sequence:

1. Back up the database and any consultation objects needed for retention.
2. Stop the API and transcription workers; finish or stop active
   consultations first.
3. Run `backend/database/phase_3_cleanup.sql` once. It deletes **all**
   appointments, emergency intakes, and any legacy consultation
   table/archive rows, and releases `BOOKED` slots. It preserves `BLOCKED`
   slots, schedules, patients, doctors, authentication records and
   signatures. Unexpected dependencies cause the script to abort rather than
   cascade-delete unrelated data.
4. Run `backend/database/phase_3.sql` (after Phase 2.2's schema). It
   renames/removes columns, adds the `specialty_id` foreign key, normalizes
   the four supported specialty names, and replaces the atomic booking RPC
   with its new signature and permissions. It refuses to run the initial
   switch while old appointments/emergencies still exist. The schema
   migration itself can be rerun safely, but the cleanup script always
   deletes all visits again if rerun.
5. Deploy backend and frontend together, restart workers, and reload browser
   tabs (stale draft keys otherwise persist).
6. Verify on the target environment: text-only booking, a catalogue
   emergency case, location-filtered slots, doctor start/consent, transcript
   editing, SOAP generation, signing, and the patient's completed
   consultation view.

Commands (from the repository root, using the existing migration runner):

```powershell
backend/.venv/Scripts/python.exe backend/scripts/apply_migration.py backend/database/phase_3_cleanup.sql
backend/.venv/Scripts/python.exe backend/scripts/apply_migration.py backend/database/phase_3.sql
```

Each script runs inside a transaction; the same files can alternatively be run
directly in the Supabase SQL editor. After a successful reset, rollback
requires restoring the backup — deploying the old application code alone
cannot restore deleted visits or columns.

Database cleanup does **not** delete local/S3 transcripts, SOAP, signed
snapshots or transcription-job files. Those objects become detached from the
deleted visits, and new appointment UUIDs prevent their accidental reuse, so
they must be preserved or removed separately under the desired retention
policy. Doctor signature objects must be retained regardless.

### Verification and limits

Backend regression tests (`backend/tests/test_phase3.py` and the related
booking/patient/consultation suites) cover catalogue ranges, severity floors,
text-only and unsupported inputs, specialty filtering, booking metadata,
shared appointments, location filtering, consent, transcript/SOAP storage and
signing. Frontend flow coverage is in `frontend/tests/patient-flows.spec.js`
(booking, draft restoration, editing, doctor consultation UI).

Automated tests use stubbed models and database clients, so they do not
establish clinical accuracy, prove live SQL execution against a real
database, concurrent-booking behavior, or provider availability. The
catalogue's clinical completeness and the Normal mapping chosen for moderate
symptoms require clinical review before claiming complete specialty coverage.
The rollout smoke checks listed above must still be run against the target
database.

This phase supersedes Phase 2's historical `history` and
`legacy_consultation_id` contracts. Completion is recorded from the project
owner's confirmation; no migrations or application tests were rerun for this
documentation-only update.
