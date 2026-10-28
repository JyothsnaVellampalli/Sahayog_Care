# Sarvam speech transcription and SOAP drafts

Sarvam is the only speech-to-text provider. Browser SpeechRecognition, local
Whisper and the local speaker heuristic have been removed. The browser uses
MediaRecorder only to capture audio; recognition runs through the backend.

## Configuration

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

## Flow

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

## SOAP

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

## Sign and close

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

## Verification

- Frontend: `npm.cmd run build` from `frontend`.
- Backend: `python -m pytest tests/test_sarvam.py tests/test_soap.py tests/test_soap_graph.py -q` from
  `backend` with dependencies installed. Tests use mock HTTP, without real audio.
- Manual: record two or three consenting speakers mixing languages, stop, check
  turns and timestamps, reload, edit text, and generate SOAP. Test upload failure
  and retry, microphone denial, silence, and another recording in the same visit.

Official API reference:
https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/how-to/enable-speaker-diarization
