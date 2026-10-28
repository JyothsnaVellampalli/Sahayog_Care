# Phase 2 — Doctor portal — Progress

## Current decisions and implementation — 2026-10-27

This section supersedes the historical implementation notes below, especially
references to Whisper, plain/roles modes, local diarization and a SOAP placeholder.

### Speech capture and speaker separation

- Sarvam is now the only speech-to-text provider. Removed browser
  SpeechRecognition, faster-whisper, PyAV/numpy speech dependencies and the local
  two-speaker heuristic. MediaRecorder captures audio but does no recognition.
- Record -> Stop -> Sarvam batch upload -> status polling -> saved editable
  transcript. Batch processing is required for speaker diarization; this is not
  live partial-text streaming.
- Saaras v4 uses codemix, automatic language detection, timestamps and automatic
  speaker count. Hindi/English and Telugu/English speech stays in its original
  scripts in the UI. The user confirmed multilingual transcription and speaker
  differentiation are working satisfactorily.
- Neutral Person 1, Person 2, Person 3 labels are scoped to each recording.
  Doctor/patient role inference is explicitly deferred. No voice identity is
  assumed across recordings. Historical transcripts remain readable.
- Upload retries retain audio in the current tab; uploaded job identity supports
  polling after refresh. Backend job metadata prevents duplicate appends for a
  completed recording. Audio is sent to Sarvam and not persisted locally by the
  application; consent text reflects this cloud processing decision.
- SARVAM_API_KEY remains server-side. Optional model, timeout and upload size
  settings are documented in backend/.env.example. Existing signature, consent,
  manual notes and transcript editing remain available.

### English translation and SOAP via LangGraph

- UI follow-up: stopping recording now automatically continues through saved
  transcription, English translation and SOAP generation. Removed the normal
  Generate/Regenerate SOAP button; a Retry summary action appears only on failure.
  Saved transcript edits also refresh the summary automatically, and opening a
  saved transcript prepares its transient summary.
- SOAP uses one shared section with four full-width rows and bold titles.
  Edit summary enables all four rows; Apply edits updates the displayed draft
  and Cancel retains the previous draft. These edits are page-local, unsigned,
  and replaced by a new transcript version; durable clinical-note saving remains
  outside this change. Recording and transcript edits are disabled during summary
  editing to avoid overwriting changes in progress.

- Added app/doctor/soap_graph.py and translation_prompt.txt. Generate SOAP now
  executes validate_input -> deidentify -> translate_to_english -> generate_soap
  -> validate_soap through a compiled LangGraph, matching the booking workflow's
  orchestration and invocation-local context pattern.
- Translation is a dedicated LLM call through the existing OpenRouter adapter,
  followed by a separate SOAP call. Both use the existing OPENROUTER_MODEL and
  API key; no additional translation credentials or dependencies are required.
- Translation preserves turn IDs/order, neutral speaker distinctions and
  recording boundaries. The prompt preserves negations, questions, uncertainty,
  numbers, units and medications. Invalid/missing/reordered turns fail before
  SOAP. Original transcript storage/UI is unchanged; English text is transient.
- De-identification runs before translation and again on translated text. The
  existing regex/optional Presidio limitations still apply to multilingual PII.
- SOAP selects concise English excerpts into Subjective, Objective, Assessment
  and Plan. Strict schema checks and per-turn excerpt checks reject unsupported
  output. Checks ground SOAP in the English translation, not its semantic
  equivalence to the original; translation fidelity still needs human review.
- No doctor/patient roles, unstated diagnoses or treatments are inferred.
  Missing sections remain empty. Drafts are unsigned, not persisted, and cleared
  after transcript changes. The button reports translation and generation work.

### LangSmith observability

- Reuses book_appointment/tracing.py initialization and base run configuration,
  including the existing LangSmith project, endpoint and credentials.
- Run name/workflow: doctor_consultation_soap; tags: doctor, translation, soap;
  a fresh run UUID identifies each execution. Each graph node produces a span.
- Trace state contains stage status and counts only. Raw transcripts, translated
  turns, drafts and adapters stay outside graph state/config in an isolated
  ContextVar. Provider error bodies are suppressed at the model boundary.
- Tracing remains optional via existing LANGSMITH settings. No graph checkpoints
  or automatic model retries are introduced. Two sequential model calls add
  latency and cost; each uses the shared adapter timeout.

### Verification and remaining work

- Sarvam accepted the configured key and v4 job parameters in the previous
  connectivity check; the user subsequently confirmed speech/voice behavior.
- Added mocked Sarvam contract tests and SOAP graph tests for translation order,
  original-text preservation, incomplete translations, neutral speakers,
  trace-safe state and existing SOAP validation behavior.
- Frontend production build verified after the SOAP button update.
- Backend tests could not run on this workstation: the Python launcher reports
  no installed Python and the existing venv targets a missing installation.
  Run the documented pytest checks after restoring Python and dependencies.
- A real translated SOAP generation and LangSmith trace inspection remain to be
  verified in the running environment. No real consultation was sent in testing.
- Existing dev-stage doctor authentication, S3 activation, location filtering
  and patient theme work below remain separate outstanding items.

See docs/DoctorSpeechAndSOAP.md for configuration and the current end-to-end flow.

## Historical Phase 2.1 foundation (superseded speech/SOAP details)

Status: Complete (pending user confirmation)

### Done When (from docs/Workflow.md) — checklist

- [x] Doctor can sign in with their phone number alone (role `doctor`). Every
      doctor is pre-seeded with a unique phone number; no password or OTP.
- [x] Digital signature is required before opening a consultation. A doctor
      uploads a PNG/JPG (< 500 KB); it is stored via the storage service and a
      signature gate blocks the consultation screens until one is on file.
- [x] Doctor home shows the day's consultations, with Today / This week / Custom
      date ranges and status filters (All / Scheduled / In progress / Completed).
- [x] Consultation view shows collapsible patient details (symptoms, history,
      allergies, vitals), a recording consent checkbox, and a listening
      animation while capturing audio.
- [x] Audio is transcribed with a local, swappable speech-to-text engine
      (faster-whisper). The transcript is editable and appendable, and is stored
      as JSON via the storage service.
- [x] Global styles live in a single tokens file and are reused across portals.

### Authentication note (dev-stage compromise)

Per the agreed scope, the only compromise for now is **auth verification**.

Doctors are identified by **phone number alone** — no password, no OTP, and no
Supabase Auth user. Each doctor row is pre-seeded with a unique phone number
(migration `backend/database/phase_2_1_doctor_phones.sql`, scheme
`+9190000000NN`); signing in is a lookup by phone that returns the doctor
profile. The sign-in response carries no session token.

(The patient portal still uses phone + password; only the doctor portal was
simplified to phone-only on request.) This is a deliberate dev-stage shortcut —
a real deployment would add proper verification (OTP or SSO) and server-side
authorization on the doctor endpoints.

### What was built

#### Database (`backend/database/phase_2_1.sql`, applied)

- `doctors` gained: `phone` (unique), `email`, `auth_user_id`, `signature_key`,
  `signature_uploaded_at`.
- New `consultations` table: `id`, `appointment_id`, `doctor_id`, `patient_id`,
  `slot_id`, `status` (SCHEDULED / IN_PROGRESS / COMPLETED / CANCELLED),
  `severity`, `symptoms` (jsonb), `history`, `allergies`, `vitals`,
  `consent_recorded`, `transcript_key`, `started_at`, `completed_at`, timestamps,
  plus supporting indexes.

#### Backend

- `app/storage.py` — unified storage interface (`put_bytes` / `get_bytes` /
  `delete` / `put_json` / `get_json`). Uses S3 (boto3) when AWS env vars are
  configured, otherwise a local filesystem fallback at `backend/storage/`.
- `app/doctor/service.py` — doctor `identify` (phone-only lookup returning the
  profile; no password/token), `save_signature`
  (validates type + size), `has_signature`, `backfill_consultations_for_doctor`
  (derives consultation rows from booked appointments), `list_consultations`
  (date range + status filters), `get_consultation` (full detail),
  `start_consultation` (requires consent, moves to IN_PROGRESS).
- `app/doctor/transcription.py` — `TranscriptionEngine` protocol +
  `FasterWhisperEngine` (lazy-loaded, degrades gracefully if the model/ffmpeg is
  missing). The engine decodes the audio once and returns timed segments plus
  the waveform. Two transcript modes (``settings.transcript_mode``):
  - **`plain`** (v2, default) — the recognized speech is folded into one
    continuous, punctuated text block (no speaker roles). A single-speaker
    recording stays a single block instead of being split into fake turns.
  - **`roles`** (v1) — automatic Doctor/Patient diarization, one segment per
    detected turn. Switch back with `TRANSCRIPT_MODE=roles`.
  Transcript storage (load / save / append / edit, marking edited segments) is
  shared by both modes. A segment's `speaker` is `null` in plain mode.
- `app/doctor/diarization.py` — lightweight **local** 2-speaker diarizer used by
  the `roles` mode (numpy only; no pyannote / PyTorch / gated models, per the
  data-residency constraint). Builds a compact spectral fingerprint per segment
  (log-energy mel-ish bands + spectral centroid), clusters into two speakers
  with a tiny k-means, and maps the earliest-speaking cluster to "Doctor".
  Best-effort, not biometric — every line stays editable.
- `app/doctor/router.py` — `/api/doctors` endpoints: `lookup`, `identify`
  (phone-only sign-in), signature `GET`/`POST`, consultations list + detail +
  `start`, transcript `GET`, `transcribe` (audio upload; speaker auto-detected),
  and segment append/edit.
- Config: AWS/S3 settings + whisper model/device/compute/language.
- Dependencies pinned and installed: `boto3`, `python-multipart`,
  `faster-whisper`, `av==13.1.0` (see note below), `numpy`.

> **PyAV pin:** `faster-whisper` 1.2.1 declares only `av>=11`, but its audio
> decoder calls `av.open(..., metadata_errors="ignore")`, an argument PyAV 14
> removed. With a newer PyAV, transcription fails at decode time with
> `open() got an unexpected keyword argument 'metadata_errors'`. Pinning
> `av==13.1.0` resolves it.

#### Frontend

- `src/theme.css` — single source of truth for design tokens (teal primary,
  surfaces, status colours, spacing, radii). `index.css` imports it and defines
  shared `.pill--*` and `.btn--*` building blocks.
- `src/auth/DoctorAuth.jsx` — doctor auth context (persisted profile; no token).
- Doctor screens under `src/pages/doctor/`:
  - `DoctorLogin.jsx` — single phone-number field (phone-only sign-in).
  - `DoctorPortal.jsx` — portal shell (header, nav, sign out).
  - `SignatureGate.jsx` — signature upload with preview + requirements.
  - `ConsultationsList.jsx` — date range + status filters, severity-coloured
    cards.
  - `ConsultationView.jsx` — collapsible details, consent + start, mic circle
    with listening animation, editable/appendable transcript, SOAP placeholder.
    Renders both transcript shapes: one continuous block (plain mode) or
    speaker-labeled rows (roles mode).
  - `useAudioRecorder.js` — MediaRecorder + Web Audio level metering.
  - `consultationMeta.js` — shared severity/status/formatting helpers. Severity
    uses the app-wide triage categories (Emergency / Severe / Normal).
- `App.jsx` — doctor routes + `RequireDoctor` guard (redirects to the signature
  gate until a signature is on file). Landing page routes the Doctor profile to
  `/doctor/login`.

### Verification

- Backend unit tests: `pytest -q` — 11 passed.
- Live API walkthrough (uvicorn on 127.0.0.1:8000): doctor identify (seeded
  phone → profile; unknown phone → clean error; response carries no token) →
  signature status → consultations list (today + range) → consultation detail →
  transcript append (2 segments) → edit (segment marked `edited`) → fetch.
  Transcript persisted as JSON via the local storage backend.
- Frontend production build (`npm run build`) is clean.
- Live transcription + diarization: a synthesized two-voice dialogue (Windows
  SAPI David/Zira) POSTed to `/transcribe` returned accurate text with automatic
  speaker labels — 3 of 4 lines correctly attributed, the 4th mislabeled (an
  expected limitation of lightweight spectral clustering on short clips, which
  is why labels stay editable). No `metadata_errors` crash.
- The diarizer's clustering is unit-checked on a synthetic 2-tone signal
  (alternating segments → Doctor/Patient).

### Follow-up fixes (post-initial 2.1)

- **Transcription crash fixed** — pinned `av==13.1.0` (PyAV 14 removed the
  `metadata_errors` arg faster-whisper 1.2.1 passes).
- **Severity standardized** — consultations now use Emergency / Severe / Normal
  (same as the booking classifier), replacing the earlier High / Moderate / Low.
  Migration `phase_2_1_severity_values.sql` converted existing rows.
- **Transcript modes** — the transcript now defaults to **plain** mode (one
  continuous punctuated block, no speaker roles) because automatic diarization
  mislabeled single-speaker recordings. The role-based mode is retained and can
  be re-enabled with `TRANSCRIPT_MODE=roles`.

### Follow-ups / known gaps

- **Diarization accuracy** (roles mode) is best-effort (lightweight numpy
  clustering). If higher accuracy is needed, upgrade to pyannote.audio (heavier;
  model download) behind the same interface.
- **SOAP clinical summary** is a placeholder — planned for Phase 2.2.
- **S3 storage** is ready but inactive until AWS credentials are provided; the
  local filesystem fallback is in use.
- **Patient-location doctor filtering** (a line added to Phase 1.4 of the
  workflow) is still not implemented — doctor suggestions don't yet filter by the
  patient's city.
- **Patient screens** still use the old blue palette; the theme-token recolour
  is deferred to the Phase 1.5 UI pass.
- A synthetic test consultation row (`a7800605-…`, IN_PROGRESS) and the test
  doctor (`+919500000001`) remain for walkthroughs; clean up before release.
