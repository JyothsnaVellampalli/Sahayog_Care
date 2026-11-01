# Phase 6: follow-up appointments, helpdesk and reports

Patient-facing visits are **appointments**. Doctors and other staff see **consultations**. Both refer to the same `public.appointments` row; there is no separate consultations table. This phase adds no model calls or summaries.

## Setup

After the existing migrations through `consultation_prescriptions.sql`, run from `backend`:

```powershell
.venv/Scripts/python.exe scripts/apply_migration.py database/phase_6_followups_reports.sql
```

Restart the API and frontend after deploying the code. The migration is additive and rerunnable, including databases that already contain the demo history report table. It does not change pharmacy stock or signed clinical content.

The landing page now includes Helpdesk. Its demonstration phone is **+919800000002**. Helpdesk uses the existing development-stage staff convention: phone-only identification, not production authentication. Patient report access requires their Supabase bearer token and ownership of the appointment.

## Follow-up flow

The symptoms step offers “This is a follow-up appointment” and a selector for the patient's completed appointments. “Book follow-up” from a completed appointment preselects it. Unchecking the option creates an unrelated appointment. Drafts retain the choice.

The same symptoms assessment and slot booking flow runs for both choices. The booking RPC writes `appointments.linked_appointment_id` atomically with the booking. The database rejects links to another patient's record, non-completed records, cycles, or records completed after the new appointment was created. A recorded link cannot be replaced or cleared. Retries with a different link fail rather than silently reusing the booking.

Emergency intake records retain the link too; the existing manual assignment RPC copies it to the appointment when staff assign a slot. Emergency triage continues to take precedence over follow-up booking.

Patient, doctor and helpdesk detail screens link to the previous related visit in a new tab. Following these links traces a series of visits. Completed doctor views read the saved prescription directly, including when a different doctor handled the previous consultation.

## Helpdesk

Helpdesk lists consultations across patients and doctors, with doctor, specialty, day and time filters and 50-row pagination. Dates/times use the browser's local timezone, consistent with the doctor portal. It defaults to today.

The detail page uses the doctor portal's patient overview and SOAP styles. It displays symptoms, saved SOAP (labelled draft or signed), medicines and signature when present. It has no recording, SOAP editing, prescription editing, stock or signing actions. Reports can be added independently of clinical status.

## Reports

The shared Reports dialog supports a carousel, PDF/image preview, downloads, loading/retry states, keyboard dismissal and focus restoration. The assigned doctor and helpdesk may upload PDF, PNG or JPEG reports up to 10 MB. Patients can view/download only. Other doctors may read related reports but cannot upload to a consultation assigned to someone else.

`consultation_reports` links metadata to `appointments.id`. New uploads use unique storage keys in `reports/<appointment-id>/<report-id>.<extension>` through the existing S3/local storage adapter. Reads are scoped to both appointment and report IDs; object keys and public bucket URLs are not exposed. The table uses RLS and service-role access. The file endpoint checks access again and disables caching.

Historical demo JSON reports appear as textual findings in the same carousel. They are not radiology image files. Uploads do not change signed snapshots, prescription review state or stock. On an ambiguous database failure, the uploaded object is retained so a potentially committed report never points to a deleted file; refresh the list before retrying.

## Verification

`scripts/verify_phase6.py` runs the migration twice and tests booking/link/report constraints in a transaction that rolls back everything. Backend tests in `tests/test_phase6.py` cover ownership, report read/upload permissions, file checks and helpdesk reads. Frontend `tests/phase6.spec.js` covers follow-up booking, report navigation and patient read-only access, helpdesk filters, upload and mobile layout. Existing booking, consultation-processing, prescriptions and pharmacy regression suites remain applicable.
