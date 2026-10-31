# Consultation processing and storage

After Stop, the browser uploads the recording and the backend commits a durable
Supabase job before acknowledging it. The doctor can select and edit medicines
during transcription and SOAP generation. Once the upload is acknowledged,
closing the screen does not cancel processing. Reopening reads job status,
transcript, saved SOAP, and the prescription draft from their respective stores.
The server must remain running; expired job leases recover after a restart.

Transcription completion and the next SOAP job are committed in one database
transaction. The SOAP worker runs the translation/SOAP graph and publishes its
result pointer only if it still owns the lease. Model processing has a four-minute
deadline; failures expose Retry SOAP. If a transcript exists without an active
job, Generate SOAP is available. Reading a consultation never starts a model call.

Medicine drafts autosave independently of SOAP, including incomplete instructions
and empty prescriptions. Final review requires the current SOAP. Signing checks
the saved prescription under the appointment lock, then reserves stock and closes
the appointment in the existing transaction. Closed prescriptions cannot be edited.
Reservations include both brand and medicine IDs, with a database constraint
ensuring the pair matches the catalogue. Stock is reserved for the specific brand:
available quantity excludes locks, dispensing reduces physical stock, and release
returns availability without changing physical stock.

## Storage

- Supabase `consultation_prescriptions`: appointment, doctor, review/version state.
- Supabase `consultation_prescription_items`: appointment, medicine and brand foreign
  keys, quantity, strength/form, dose, frequency, duration, instructions and display metadata.
- Supabase `consultation_jobs`: queue, leases, errors and temporary encoded audio.
  Audio is removed from the row when transcription succeeds; failed jobs retain it for retry.
- Supabase `consultation_recordings`: Sarvam job ID and upload/provider checkpoint.
- S3: transcripts, SOAP results and signed clinical/signature snapshots. New signed
  snapshots do not contain prescriptions; doctor, patient and pharmacy reads compose
  the snapshot with the relational prescription. Patients still receive signed records only.

The old `transcription_jobs/` S3 folder held Sarvam job IDs and upload checkpoints,
allowing interrupted uploads/polls to resume. New checkpoints use Supabase. Legacy
checkpoints and pending audio objects remain readable so existing work can finish.
Appointment/job rows retain object keys to retrieve the correct clinical documents.

## Deployment

Apply `backend/database/consultation_processing.sql`, then
`backend/database/consultation_prescriptions.sql` after Phase 4.3. Run
`backend/database/pharmacy_reservation_medicines.sql` to backfill and enforce medicine
identity on reservations. Run
`backend/scripts/migrate_consultation_prescriptions.py` to import legacy prescriptions.
Imports are insert-only and also happen on first read; originals are retained.
Restart/redeploy the API and frontend with the new code. Do not reapply Phase 4.3
alone after the prescription migration because it replaces the signing function;
reapply the prescription migration afterward if needed.

Verification: `verify_consultation_processing.py` and
`verify_stock_transactions.py` use rollback-only database fixtures. Browser tests
in `consultation-processing.spec.js` cover leaving/reopening, early medicine entry,
and explicit SOAP recovery on mobile and desktop.
