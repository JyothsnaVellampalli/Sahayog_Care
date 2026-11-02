# Phase 6 - Follow-up appointments, helpdesk and reports - Progress

Status: Complete.

### Done When - checklist

- [x] A follow-up consultation record is recorded with the previous linked
  appointment/consultation and can be viewed in UI.
- [x] A reports UI for doctor and helpdesk portal; patient can only view the
  reports.

### Model

Patient-facing visits are **appointments**. Doctors and other staff see
**consultations**. Both terms refer to the same `public.appointments` row —
there is no separate consultations table. This phase adds no model calls or
AI summaries; it is DB records and UI linking only, as scoped in Workflow.md.

### Delivered - follow-up flow

- The symptoms step offers "This is a follow-up appointment" with a selector
  listing the patient's completed appointments. Starting "Book follow-up"
  from an already-completed appointment preselects that appointment.
  Unchecking the option creates an unrelated (non-linked) appointment.
  Browser drafts retain the follow-up choice.
- The same symptoms assessment and slot-booking flow runs for both a fresh
  appointment and a follow-up. The booking RPC writes
  `appointments.linked_appointment_id` atomically together with the booking,
  so the link and the slot reservation cannot diverge.
- Database-level constraints on the link: rejects linking to another
  patient's record, to a non-completed record, to a cycle, or to a record
  that was completed *after* the new appointment was created. A recorded link
  cannot later be replaced or cleared. A retry of the booking call with a
  different link fails outright rather than silently reusing the original
  booking.
- Emergency intake records also carry the link. The existing manual
  doctor/slot assignment RPC copies the link from the emergency intake onto
  the appointment when staff assign a slot. Emergency triage continues to
  take precedence over follow-up booking (emergency routing still runs
  first).
- Patient, doctor and helpdesk detail screens each show a link to the
  previous related visit, opening it in a new tab. Following these links
  traces an entire chain of related visits. A completed doctor view reads the
  saved prescription directly from storage, including cases where a
  *different* doctor handled the previous linked consultation.

### Delivered - helpdesk portal

- Added a new staff portal, reachable from the landing page as **Helpdesk**.
  Its demo phone is `+919800000002`, using the existing development-stage
  staff convention of phone-only identification (not production
  authentication).
- Helpdesk lists consultations across **all** patients and doctors (unlike
  the doctor portal, which is scoped to one doctor), with filters for doctor,
  specialty, day and time, plus 50-row pagination. It defaults to today.
  Dates/times render in the browser's local timezone, consistent with the
  doctor portal's existing behavior.
- The helpdesk detail page reuses the doctor portal's patient-overview and
  SOAP styling. It displays symptoms, the saved SOAP (explicitly labelled
  draft or signed), medicines and the doctor's signature when present.
- The helpdesk detail page is intentionally read-only for clinical content:
  it has **no** recording, SOAP editing, prescription editing, stock, or
  signing actions. Reports, however, can be added from helpdesk independently
  of the consultation's clinical status.

### Delivered - reports

- Added a shared Reports dialog (same component used by doctor, helpdesk and
  patient views) supporting a carousel, PDF/image preview, downloads,
  loading/retry states, keyboard dismissal and focus restoration.
- The consultation screen gained a Reports button at the top-right corner of
  the speech/recording area, available to the assigned doctor and to
  helpdesk. Patients can reach the same reports from their appointment view
  in the patient portal.
- Upload permissions: the assigned doctor and helpdesk staff may upload
  PDF, PNG or JPEG reports up to 10 MB. Patients can only view/download, never
  upload. Other doctors (not the one assigned to that consultation) may read
  related reports but cannot upload to a consultation assigned to someone
  else.
- New table `consultation_reports` links report metadata to
  `appointments.id`. New uploads use unique storage keys in the form
  `reports/<appointment-id>/<report-id>.<extension>` through the existing
  S3/local storage adapter (the same adapter used for transcripts/SOAP/
  signatures).
- Reads are scoped to both the appointment ID and the report ID; raw object
  keys and public bucket URLs are never exposed to the client. The table uses
  RLS with service-role access, and the file-serving endpoint re-checks
  access on every read and disables caching.
- Historical demo JSON reports (pre-existing seeded data) appear as textual
  findings inside the same carousel alongside uploaded files — they are not
  radiology image files, just older textual demo content rendered in the same
  UI.
- Uploads do not change signed snapshots, prescription review state, or
  stock. On an ambiguous database failure during upload, the uploaded storage
  object is deliberately retained rather than deleted, so that a report which
  may have actually committed to the database never ends up pointing at a
  deleted file; the UI should refresh the report list before retrying an
  upload in that situation.

### Setup / migration

After the existing migrations through `consultation_prescriptions.sql`, run
from `backend`:

```powershell
.venv/Scripts/python.exe scripts/apply_migration.py database/phase_6_followups_reports.sql
```

The migration is additive and rerunnable, including against databases that
already contain the demo history report table. It does not change pharmacy
stock or signed clinical content. Restart the API and frontend after
deploying the migrated code.

### Verification

- `scripts/verify_phase6.py` runs the migration twice and tests
  booking/link/report constraints inside a transaction that rolls back
  everything, so it leaves no residue in the target database.
- Backend tests in `backend/tests/test_phase6.py` cover ownership, report
  read/upload permissions, file checks and helpdesk reads.
- Frontend tests in `frontend/tests/phase6.spec.js` cover follow-up booking,
  report navigation and patient read-only access, helpdesk filters, upload
  and mobile layout.
- Existing booking, consultation-processing, prescriptions and pharmacy
  regression suites remain applicable and were not invalidated by this phase.

### Implementation and verification references

See [Phase 6 implementation and rollout](../Phase6.md) for the full setup,
flow, helpdesk and reports detail, and verification notes summarized above.
This phase builds on the shared appointment model from Phases 1–4 and the
consultation processing/prescription storage described in
[Consultation processing](../Consultation-processing.md); it introduces no
new model calls.
