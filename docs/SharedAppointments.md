# Shared appointments and consultations

`appointments` is the active visit record for both portals. The patient's
appointment ID is also the doctor's consultation ID. `BOOKED` is displayed as
`SCHEDULED` in the doctor API; starting the consultation writes `IN_PROGRESS`
to the same appointment. Patient demographics come from `patients`, and doctor
assignment and time come from `slots`. Symptoms, severity, history, consent,
and consultation timestamps live on the appointment.

Previously, reading the doctor list inserted separate `consultations` rows,
copied only the reason-derived severity, and allowed the two statuses to drift.
The list now performs reads only, with doctor and date filters in the database.

## Database rollout

Stop the old backend, back up the database, and run
`backend/database/phase_2_2_unified_appointments.sql` once, after the existing
Phase 1.4 and Phase 2.1 migrations. Start the updated backend and frontend
together after the migration succeeds. From the repository root:

```powershell
backend/.venv/Scripts/python.exe backend/scripts/apply_migration.py backend/database/phase_2_2_unified_appointments.sql
```

The migration copies clinical fields and visit state onto appointments and
renames the old table to `consultations_legacy_archive` for recovery/audit.
No active application query reads or writes the archive. It deliberately aborts
the entire transaction if historical consultation rows are duplicated, orphaned,
or disagree with their appointment's patient/slot/doctor; reconcile those records
before rerunning. It must not guess which clinical record is authoritative.
Old symptom details that were never stored cannot be reconstructed by migration.

`legacy_consultation_id` preserves old links and the storage namespace for
existing transcript, SOAP, and transcription-job JSON. New visits use their
appointment ID for those objects. No S3 objects need moving.

## Booking

The intake graph returns its selected symptom details alongside the existing
classification and de-identified text. The frontend submits those fields with
the selected slot, patient, and a UUID idempotency key. Repeated attempts for
the same selection reuse that key. Booking now requires a patient.

The `book_appointment` database function locks the slot, inserts the appointment,
and marks the slot booked in one transaction. An insertion failure cannot leave
a newly reserved slot without an appointment. Retries return the same record;
competing bookings cannot claim the same slot. Past slots are excluded from
suggestions and rejected at booking. The RPC is callable by the server's
service role only.

## Emergencies

Triage writes `emergency_intakes`, without assigning a doctor or reserving a
slot. Rows with `is_met = false` lead the patient's list and the doctors' shared
unassigned queue, including when a doctor filters scheduled visits by date or
status. These cards cannot open a consultation before assignment.

After staff handle an emergency and manually choose a doctor and an open slot,
call `POST /api/doctors/{doctor_id}/emergency-intakes/{intake_id}/assign` with
`patient_id`, `slot_id`, and a UUID `idempotency_key`. This is an explicit API
operation; no automatic assignment or staff assignment screen was introduced.
The endpoint checks the chosen slot belongs to the doctor. The same booking
transaction copies the intake's symptoms/history, creates the appointment,
links its `emergency_intake_id`, and sets `is_met`/`met_at`. The pending card then
disappears and the assigned doctor's scheduled consultation appears.

## Verification

```powershell
cd backend
.venv/Scripts/python.exe -m pytest tests/test_shared_appointments.py tests/test_soap_storage.py tests/test_intake_graph.py tests/test_soap.py tests/test_soap_graph.py tests/test_sarvam.py -q -p no:cacheprovider
cd ../frontend
npm.cmd run build
```

After deploying the migration, book a future slot as a patient and verify the
same ID, symptom labels, age, gender and history in the assigned doctor's portal.
Start it with consent and verify `IN_PROGRESS` in the patient's list. Verify an
older unseen emergency is still first, then manually assign it and confirm it
is replaced by one appointment. Retry the booking with the same idempotency key
and confirm no duplicate row; compete for a slot from two patients and confirm
only one succeeds. Check a migrated visit's saved transcript remains readable.
