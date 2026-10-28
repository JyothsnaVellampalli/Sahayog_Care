# Phase 2 - Consultation Scribe - Progress

## Phase 2.1 - Doctor portal, signature and consultation foundation

Status: Complete (per docs/Workflow.md).

### Delivered

- Doctor sign-in uses a pre-seeded phone number and returns a doctor profile.
  This remains development-stage identification: no password, OTP, Supabase Auth
  user or session token. Patient login still uses phone and password. Production
  doctor authentication and endpoint authorization remain outstanding.
- Doctors upload a PNG/JPG signature smaller than 500 KB. The signature gate
  requires an uploaded signature before consultation screens can be opened.
- The portal opens today's consultations, with Today / This week / Custom date
  ranges and All / Scheduled / In progress / Completed status filters.
- Consultation screens show patient details, symptoms/history, consent and
  recording controls. Transcripts are stored as JSON and can be edited when
  transcript display is enabled. Phase 2.2 below documents the current provider,
  shared appointment lifecycle and transcript-display setting.
- Shared teal design tokens, responsive portal navigation, signature preview,
  recording animation and audio-level metering were added. Patient styling and
  city-based doctor filtering were completed in [Phase 1.5](Phase1.md#phase-15---patient-ui-and-local-doctor-suggestions).
- Storage uses the shared JSON/byte interface in app/storage.py: configured S3
  or the local backend/storage fallback. Active storage depends on environment
  configuration; the original local-only rollout is not a current restriction.

### Foundation migrations and implementation history

- phase_2_1.sql added doctor phone/email/auth linkage and signature fields, and
  originally introduced a separate consultations table. Phase 2.2 replaces that
  active table with appointments and retains a legacy archive; do not backfill
  separate consultation rows when reading lists.
- phase_2_1_doctor_phones.sql seeded unique doctor phone numbers (scheme
  +9190000000NN). phase_2_1_severity_values.sql standardized Emergency / Severe /
  Normal in place of High / Moderate / Low.
- The original local faster-whisper engine, PyAV 13.1.0 compatibility pin,
  numpy two-speaker heuristic and plain/roles transcript modes were replaced by
  Sarvam in Phase 2.2. They are historical implementation details, not setup
  requirements. Doctor/patient speaker-role inference is no longer performed.
- DoctorAuth, DoctorLogin, DoctorPortal, SignatureGate, ConsultationsList,
  ConsultationView, useAudioRecorder and consultationMeta provide the frontend
  foundation. app/doctor now owns identity/signatures; app/consultation owns
  the clinical workflow, while existing /api/doctors URLs remain compatible.

### Verification recorded for the foundation

- Initial backend suite: 11 passing tests. Live walkthrough covered phone
  identification, signature status, date-filtered lists, consultation details,
  and transcript append/edit/read using local storage. Frontend build passed.
- Historical local speech checks used a synthetic two-voice recording and a
  two-tone clustering test. These do not validate the current Sarvam provider.
- A synthetic IN_PROGRESS consultation (a7800605-...) and test doctor
  (+919500000001) were recorded as cleanup items; their current presence has not
  been rechecked. Any surviving old visit is subject to the migration below.

## Phase 2.2 - Saved SOAP, doctor approval and consultation completion

Status: Complete (per docs/Workflow.md); live validation limitations are below.

### Done When - checklist

- [x] Generate English SOAP from the saved consultation transcript using the LLM.
- [x] Persist the summary and allow reviewed edits to be saved.
- [x] Sign and close the consultation after doctor review.
- [x] Use LangGraph for translation/SOAP stages with LangSmith tracing.

Opening a consultation reads its saved summary. Generation/regeneration is
explicit, and Apply edits persists the draft. Earlier progress notes describing
automatic generation, page-local-only edits and an unfinished SOAP placeholder
are superseded by the implementation below.

### Shared appointments and consultations

`appointments` is the active visit record for both portals. The patient's
appointment ID is also the doctor's consultation ID. `BOOKED` is displayed as
`SCHEDULED` in the doctor API; starting the consultation writes `IN_PROGRESS`
to the same appointment. Patient demographics come from `patients`, and doctor
assignment and time come from `slots`. Symptoms, severity, history, consent,
and consultation timestamps live on the appointment.

Previously, reading the doctor list inserted separate `consultations` rows,
copied only the reason-derived severity, and allowed the two statuses to drift.
The list now performs reads only, with doctor and date filters in the database.

#### Database rollout

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

#### Booking

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

#### Emergencies

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

#### Verification

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

### Sarvam speech transcription and SOAP drafts

Sarvam is the only speech-to-text provider. Browser SpeechRecognition, local
Whisper and the local speaker heuristic have been removed. The browser uses
MediaRecorder only to capture audio; recognition runs through the backend.

#### Configuration

App-level settings live in `backend/app/config.py`. Set
`SHOW_SPEECH_TRANSCRIPTS=false` in `backend/.env` (the default) to hide the
transcript and its editing controls in the doctor portal and omit transcript
segments from newly signed snapshots. Set it to `true` during technical
validation, restart the backend, and reload the page to show them again.
The UI reads the flag from `/api/settings`, which exposes no credentials.
Recording, transcription storage, SOAP, signature display and upload/retry
controls work in either mode. This is a display/debug flag, not an access-control
setting. Existing signed objects are not rewritten; hidden transcripts in old
snapshots are not displayed. Snapshots created without transcripts cannot later
display a frozen transcript when the flag is enabled.

Backend modules: `app/doctor` owns identity, profiles and uploaded signatures.
`app/consultation` owns the appointment lifecycle, recording/transcription,
translation/SOAP graph and prompts, saved summaries, and signing/finalization.
Consultation APIs keep their `/api/doctors/...` URLs for compatibility. The UI
continues to present consultations within the doctor portal.

Set `SARVAM_API_KEY` in `backend/.env` and restart the backend. Optional settings:
`SARVAM_STT_MODEL=saaras:v4`, `SARVAM_TIMEOUT_SECONDS=60`,
`SARVAM_MAX_AUDIO_BYTES=104857600`. The key never reaches the frontend.
Microphone capture requires HTTPS or localhost and browser permission.

#### Flow

1. Keep the existing signature, consultation and consent steps. Consent discloses
   that recorded audio is sent to Sarvam.
2. Record the conversation, then stop. There is no live transcription: Sarvam
   speaker diarization uses its batch API.
3. The backend creates a job with `mode=codemix`, `language_code=unknown`,
   diarization and timestamps enabled. Speaker count is automatically detected.
   Hindi/English and Telugu/English may be mixed; accuracy needs testing with
   representative accents, microphones and clinical vocabulary.
4. Upload through a signed URL, start the job, and poll its status. The frontend
   checks every five seconds, then offers Check again after 120 pending checks.
5. Save timestamped speaker turns to the existing editable transcript. Speakers
   are named Person 1, Person 2, Person 3, etc., in order of first appearance.
   No doctor/patient roles are inferred. Labels apply only within each recording;
   Person 1 in another recording may be a different person. Unattributed turns
   display Unidentified speaker.

The application does not persist raw audio. Failed uploads retain audio in the
current tab for retry; closing the tab loses that audio. Once uploaded, job IDs
in sessionStorage allow polling to resume on refresh. Backend job metadata lives
under `transcription_jobs/`; completed results are appended once per recording.
The transcript remains under `transcripts/`. Discarding a pending recording in
the UI does not cancel or delete a provider job. Provider retention is governed
by the Sarvam account/service policy.

Recording stops just below two hours; the backend also enforces the byte limit.
Saved historical transcripts remain readable. Manual notes and edits remain
available. There is no automatic fallback to another speech engine.

#### SOAP

Opening a consultation reads the last saved SOAP through GET `/soap`; it never
calls the LLM. Generate summary / Regenerate summary explicitly requests a new
draft from the saved transcript. Transcript changes do not overwrite a reviewed
summary automatically.
The summary has four full-width rows in one section. Edit summary enables all
rows, with Apply edits and Cancel. Apply edits persists the four SOAP arrays
through PUT `/soap`, so the reviewed draft survives reloads.

SOAP generation runs a compiled LangGraph: validate_input -> deidentify ->
translate_to_english -> generate_soap -> validate_soap. The original multilingual
transcript remains unchanged in storage and the UI. A separate translation call
through the shared OpenRouter adapter produces English text for every turn,
including already-English input. It preserves turn IDs, order, recording scope
and neutral speaker distinctions. Missing, reordered or blank translations stop
the pipeline before SOAP. Translation output is de-identified again.

The second model call selects concise English source excerpts into subjective,
objective, assessment and plan arrays. Each excerpt must occur within a single
English turn; this validates against translation, not the original-language
meaning. Translation accuracy and clinical section placement require review.
No roles, new diagnoses or treatment recommendations are inferred. The draft
is saved after validation to `soap/<consultation_id>.json`, alongside the
`transcripts/` objects, using the same configured S3 bucket and prefix (or local
storage fallback). The JSON contains only the four arrays: `subjective`,
`objective`, `assessment`, and `plan`; the consultation ID is in the filename.
Regeneration replaces the saved draft; a failed save returns an error. The
English intermediate remains transient. Manual summary edits update the saved draft.
S3 requests use a 5-second connection timeout, a 15-second read timeout, and
at most two attempts. The UI stops waiting after 120 seconds and offers Retry
summary. A browser timeout does not cancel backend work; the server may still
finish saving. Server logs report save completion/failure without draft text.
The S3 client uses path-style addressing to avoid legacy SOAP routing for the
root `soap/` prefix when `S3_PREFIX` is empty. Object keys remain unchanged.

#### Sign and close

Apply `backend/database/phase_2_2_signed_consultations.sql` after the unified
appointments migration, then restart the backend. It adds `finalised_record_key`
to appointments; existing data is retained.

The assigned doctor can select Sign and close after reviewing the summary and
applying edits. The server requires an in-progress consultation, recorded
consent, an existing SOAP draft and an uploaded signature. It writes a uniquely
named `signed_consultations/<appointment_id>/<uuid>.json` object containing the
reviewed SOAP, optional validation transcript, signature-image snapshot, doctor identity and signing
time, then conditionally sets the appointment to `COMPLETED` with its completion
time and snapshot reference. A failed object save does not close the appointment.
The signature is the uploaded image, not a cryptographic signing certificate.

Closed visits load SOAP and transcript from this fixed snapshot. The small
signature is displayed beneath SOAP, even if the doctor later replaces their
profile signature. UI recording, editing, regeneration and signing controls
are hidden. Mutation endpoints reject closed visits; completed visits cannot
be restarted. A late in-flight draft write cannot alter the signed snapshot.
Signing uses the existing development-stage doctor identity model (phone lookup,
without session-token authentication).

Both calls reuse OPENROUTER_API_KEY, OPENROUTER_MODEL and the adapter timeout.
LangSmith reuses the booking flow's LANGSMITH_TRACING, LANGSMITH_API_KEY,
LANGSMITH_ENDPOINT and project/agent/environment settings. Runs are named
doctor_consultation_soap, with one span per stage and a generated run UUID.
Only stage status and counts enter graph state; transcript, English text, model
payloads and credentials stay in invocation-local context, outside trace inputs
and outputs. There is no checkpoint persistence or automatic model retry.
Tracing can be disabled without disabling the workflow.

#### Verification

- Frontend: `npm.cmd run build` from `frontend`.
- Backend: `python -m pytest tests/test_sarvam.py tests/test_soap.py tests/test_soap_graph.py -q` from
  `backend` with dependencies installed. Tests use mock HTTP, without real audio.
- Manual: record two or three consenting speakers mixing languages, stop, check
  turns and timestamps, reload, edit text, and generate SOAP. Test upload failure
  and retry, microphone denial, silence, and another recording in the same visit.

Official API reference:
https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/how-to/enable-speaker-diarization

### Validation status and remaining work

- A previous Sarvam connectivity check accepted the configured key and v4 job
  parameters; the user subsequently confirmed multilingual transcription and
  speaker differentiation. Representative accents, clinical vocabulary and
  microphones still require evaluation.
- Mocked tests cover Sarvam contracts, translation ordering, preservation of
  original text, missing/reordered translations, neutral speakers, trace-safe
  state and SOAP excerpt validation. The commands above describe repeatable
  verification; they are not a claim that every suite ran during consolidation.
- The later Phase 1.6 regression run passed 45 backend tests, including shared
  appointments and signed consultations, plus 8 browser tests and the frontend
  build. The earlier report that Python tests could not run was superseded:
  the configured environment was accessible outside the sandbox.
- Real translated SOAP generation and a live LangSmith trace inspection remain
  unverified in these progress notes. Translation fidelity and clinical section
  placement require doctor review. No real consultation was sent in the mocked
  tests. Development-stage doctor authentication remains an open limitation.
