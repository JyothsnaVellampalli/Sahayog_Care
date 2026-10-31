# Phase 3: focused symptom catalogue

The application reads `backend/app/book_appointment/data/symptoms_2.json` directly:
132 symptoms covering Cardiology, Orthopedics, Dermatology and Gastroenterology.
The catalogue validates unique IDs/codes, severity, weight and specialty at load.
It is served through `/api/symptoms`; no separate symptom-table ingestion is needed.
The old `symptoms.json` and `symptom_categories.json` are retained as historical
files and are no longer read by the intake flow. Restart the backend after editing
the catalogue because it is cached per process.

## Behavior

- Selection is optional; text alone is sufficient. Empty intake and unknown IDs
  return 422. Duration is optional. Severity displayed in the form comes from the
  catalogue, and the backend resolves metadata itself.
- Catalogue `emergency` maps to Emergency, `severe` to Severe, and `mild`/`moderate`
  to Normal for the existing three-level routing. The original metadata remains
  available. Model interpretation may escalate based on context or free text.
  Explicit emergency/severe selections cannot be downgraded by model scores or
  patient intensity. An emergency selection still takes the emergency path if
  the model is unavailable; other model failures offer no slots.
- One combined Jev call still handles multilingual free text and specialty.
  Unsupported conditions can return no specialty instead of being forced into
  one of the four. Insufficient information offers no slots.
- Specialty choices are filtered by existing DB codes CARD, ORTH, DERM, GAST.
  Other specialty and doctor records remain intact. Location filtering remains.
- `appointments.symptom_text` replaces `history` throughout both portals and the
  booking RPC. It stores the de-identified patient description, not medical history.
- Nullable `appointments.specialty_id` references `specialties.id`. The first
  assessment's ID travels with booking and is persisted when the appointment is
  created. Intake alone does not create an appointment. Emergency intake retains
  its assessment and copies its specialty during manual assignment. Patient
  appointment views join the appointment specialty rather than infer it from the
  doctor's current specialty. Normal booking validates doctor/specialty agreement.
- Consultation, transcript, SOAP and signed snapshot storage use the shared
  appointment ID. Removed columns: `legacy_consultation_id`, `allergies`, `vitals`.
  Clinical information discussed during consultation can still appear in SOAP.
- Browser drafts use a new versioned key so reused symptom IDs cannot silently
  restore old selections. Existing tabs must reload when the release switches.

## Database rollout

This is a coordinated maintenance-window switch, not a rolling migration.
Old and new application versions use different column/RPC contracts.
The SQL files are provided for the operator; they are not automatically run by
application startup.

1. Back up the database and any consultation objects needed for retention.
2. Stop the API and transcription workers; finish or stop active consultations.
3. Run `backend/database/phase_3_cleanup.sql` once. It deletes ALL appointments,
   emergency intakes, and any legacy consultation table/archive rows. It releases
   BOOKED slots but preserves BLOCKED slots, schedules, patients, doctors,
   authentication records and signatures. Unexpected dependencies abort rather
   than cascade-delete unrelated data.
4. Run `backend/database/phase_3.sql` after Phase 2.2. It renames/removes columns,
   adds the specialty foreign key, normalizes the four specialty names, and
   replaces the atomic booking RPC with the new signature and permissions.
   It refuses the initial switch while old appointments/emergencies remain.
   Schema migration can be rerun; cleanup always deletes all visits again.
5. Deploy backend and frontend together, restart workers, and reload browser tabs.
6. Verify text-only booking, a catalogue emergency, location-filtered slots,
   doctor start/consent, transcript editing, SOAP generation, signing, and the
   patient's completed consultation view on the target environment.

From the repository root, using the existing migration runner:

```powershell
backend/.venv/Scripts/python.exe backend/scripts/apply_migration.py backend/database/phase_3_cleanup.sql
backend/.venv/Scripts/python.exe backend/scripts/apply_migration.py backend/database/phase_3.sql
```

Alternatively execute each SQL file in order in the Supabase SQL editor. Each
script uses a transaction. After a successful reset, rollback requires restoring
the backup; deploying old code alone cannot restore deleted visits or columns.

Database cleanup does not delete local/S3 transcripts, SOAP, signed snapshots or
transcription-job files. They are detached from deleted visits; new UUIDs prevent
their reuse. Preserve or remove those objects separately under the desired
retention policy. Doctor signature objects must be retained.

## Verification and limits

Backend regression tests cover catalogue ranges, severity floors, text-only and
unsupported inputs, specialty filtering, booking metadata, shared appointments,
location filtering, consent, transcript/SOAP storage and signing. Frontend tests
exercise booking, draft restoration, editing, and doctor consultation UI.

Automated tests use stubbed models and database clients. They do not establish
clinical accuracy or prove live SQL execution, concurrent booking behavior or
provider availability. The supplied catalogue's clinical completeness and the
Normal mapping for moderate symptoms require clinical review before claiming
complete specialty coverage. Run the rollout smoke checks against the target DB.
