# Sahayog Care

An AI-assisted patient and doctor platform for a multi-hospital network.

- [Architecture flowcharts](docs/Architecture.md): booking and consultation flows,
  including libraries, model calls and storage.
- [Product requirements](docs/PRD.md) and [UI design](docs/UI_Design.md).
- [Workflow](docs/Workflow.md): phased delivery plan.
- [Phase 1 progress](docs/Progress/Phase1.md): patient portal and booking.
- [Phase 2 progress](docs/Progress/Phase2.md): doctor portal and consultation scribe.
- [Phase 3 progress](docs/Progress/Phase3.md): symptom catalogue and appointment schema.
- [Phase 4 progress](docs/Progress/Phase4.md): pharmacist portal, catalogue and stock.

## What works today

### Patient portal

- Sign in with phone and password through Supabase Auth, or register with name,
  age, gender, email and location. The profile popup allows name and city edits.
- Enter symptoms using a searchable selector and multilingual free text. The
  LangGraph flow validates input and de-identifies text, then makes **one Jev
  call for urgency and specialty**. It uses the original-language text without
  a separate translation call. Hinglish/Tinglish accuracy needs live evaluation.
- Emergency cases save their matched specialty and appear in the pending-care
  queue. Other cases show doctors in the patient's city and available future
  slots; severe cases include earliest-slot guidance.
- Selecting a slot creates the appointment and reserves the slot atomically.
  Idempotent retries return the same appointment; competing bookings cannot
  claim the same slot.
- My appointments includes booked visits and pending emergencies. Patients can
  edit symptoms/history before consultation starts and view/download signed
  summaries after completion. Intake drafts are scoped to the patient/browser tab.

### Doctor portal and consultation scribe

- Identify a pre-seeded doctor by phone, upload a signature, and browse today's
  consultations or filter by date and status.
- Both portals share the same appointment record and ID. Starting a consultation
  records consent and changes the appointment to IN_PROGRESS.
- Browser MediaRecorder captures audio. After stopping, **Sarvam saaras:v4**
  batch transcription produces timestamped, multilingual speaker turns with
  neutral Person 1 / Person 2 labels. There is no live transcription or inferred
  doctor/patient speaker role.
- Generate/Regenerate summary explicitly starts the SOAP LangGraph: validate,
  de-identify, **LLM call 1: English translation**, **LLM call 2: SOAP extraction**,
  then schema and source-excerpt validation. Opening a visit reads saved SOAP.
- Doctors review and save edits, then sign and close. A fixed SOAP/signature
  snapshot is saved before the appointment becomes COMPLETED. Closed visits
  are read-only; replacing the doctor's profile signature does not alter them.
- Pending emergencies have an explicit doctor/slot assignment API. A front-desk
  assignment screen remains future work.

Both graphs support optional LangSmith tracing. Signatures, transcripts, SOAP
and signed snapshots use configured S3 storage or a local filesystem fallback.

### Pharmacist portal

- Open Pharmacist from the landing page and sign in with demo phone
  `+919800000001` after the [Phase 4.1 setup](docs/Progress/Phase4.md#setup).
- Browse 90 medicines / 166 brands with combined brand, specialty, composition
  and stock filters. Random demo quantities are labelled; saved count updates
  persist in PostgreSQL. Re-importing the catalogue preserves those counts.
- Doctors review the SOAP summary and select medicines with explicit prescription
  instructions and stock quantities. Signing freezes the prescription and reserves
  its stock atomically; insufficient stock leaves the consultation open.
- Pharmacists view frozen prescriptions, mark medicines collected, or unlock an
  uncollected reservation after 24 hours. Overdue reservations are flagged, and
  inventory shows available, reserved and total stock.
- Apply the [Phase 4.3 migration](docs/Progress/Phase4.md#rollout-and-verification)
  before running the updated signing and pharmacy flows.
- Then apply the [consultation processing and prescription migrations](docs/Consultation-processing.md#deployment)
  for background transcription/SOAP and Supabase prescription drafts.

## Tech stack

Python 3.12, FastAPI, Pydantic, LangGraph, Supabase (PostgreSQL and Auth),
OpenRouter (Jev decisions and consultation LLM), Sarvam, boto3/S3,
React, Vite, LangSmith and Playwright.

## Project structure

~~~text
backend/
  app/
    main.py             API entry point and routers
    config.py           Environment-based settings
    appointments.py     Shared appointment operations
    book_appointment/   Intake graph, Jev prompts, de-identification and catalogue
    patient/            Patient identity, profile and appointment APIs
    doctor/             Doctor identity and uploaded signatures
    consultation/       Transcription, SOAP graph, review and finalization
    storage.py          S3/local storage interface
  database/             Phase SQL migrations
  scripts/              Migration runner and synthetic data helpers
  tests/                Backend regression tests
  .env.example          Configuration template
frontend/
  src/
    auth/               Patient and doctor session contexts
    components/         Shared controls
    pages/patient/      Booking, profile and appointment screens
    pages/doctor/       Consultation, recording and SOAP screens
    theme.css           Shared design tokens
  tests/                Playwright flows and accessibility checks
docs/
  Architecture.md       Mermaid flowcharts
  Workflow.md           Delivery plan
  Progress/             Phase implementation and verification notes
~~~

## Prerequisites

- Python 3.12 and Node.js/npm (developed with Node 24/npm 11).
- A Supabase project and OpenRouter API key for booking and SOAP.
- A Sarvam API key for speech transcription.
- Optional AWS credentials and a private S3 bucket; otherwise local storage is used.
- HTTPS or localhost, plus browser microphone permission, for recording.

## Backend setup

From the repository root:

~~~powershell
cd backend
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
~~~

Fill in backend/.env, apply the database migrations below, then start the API:

~~~powershell
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
~~~

Health: http://127.0.0.1:8000/health. API docs: http://127.0.0.1:8000/docs.
Never commit the real .env or expose server credentials through VITE_* variables.

### Backend configuration

See [backend/.env.example](backend/.env.example) for the complete template.
Model IDs below are code defaults and can be overridden in the environment.

| Variables | Purpose |
| --- | --- |
| APP_NAME, ENVIRONMENT, FRONTEND_ORIGINS | Service identity and allowed frontend origins. |
| SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY | Auth and server-side database access. |
| DB_PASSWORD | Direct database access for the migration runner. |
| OPENROUTER_API_KEY | Shared key for Jev decisions and consultation LLM calls. |
| SYMPTOM_CLASSIFIER_MODEL | Booking model; default typesafe/jev-1.13. |
| OPEN_ROUTER_CLASSIFIER_URL | Jev Decisions API endpoint. |
| OPENROUTER_MODEL | Consultation translation/SOAP model; default google/gemini-3.8-flash. |
| OPENROUTER_BASE_URL, OPENROUTER_TIMEOUT_SECONDS | Chat endpoint and model-call timeout. |
| SARVAM_API_KEY, SARVAM_STT_MODEL | Speech provider key and model; default saaras:v4. |
| SARVAM_TIMEOUT_SECONDS, SARVAM_MAX_AUDIO_BYTES | Speech request timeout and audio size limit. |
| SHOW_SPEECH_TRANSCRIPTS | Default false; show transcript/edit controls for validation when true. This is not access control. |
| AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, S3_BUCKET, S3_PREFIX | Optional object storage; otherwise backend/storage is used. |
| LANGSMITH_* | Optional tracing configuration for both workflows. |

### Database setup

The current consolidated SQL files are in [backend/database](backend/database).
For a fresh database, apply them in this order:

1. phase_1_3.sql: core tables, synthetic specialties/hospitals/doctors and slots.
2. phase_1_4.sql: patient login/profile fields and emergency intakes.
3. phase_1_6.sql: emergency specialty snapshot.
4. phase_2_1.sql: doctor identity/signatures and consultation fields on appointments.
5. phase_2_2.sql: signed-snapshot reference and atomic booking/emergency assignment.

For example, from backend:

~~~powershell
.venv/Scripts/python.exe scripts/apply_migration.py database/phase_1_3.sql
~~~

Repeat for the remaining files in order, or use the Supabase SQL Editor. Back up
existing databases and review their schema before applying migrations. Historical
migration filenames in progress notes describe earlier rollouts; use the current
files listed above for fresh setup. The reset_booking_data.sql utility is not a
setup migration.

To replenish synthetic future slots, run from backend:

~~~powershell
.venv/Scripts/python.exe scripts/seed_slots.py
~~~

The symptom catalogue lives in app/book_appointment/data/symptoms.json, not in
a database table. The scripts/clean_symptoms.py helper regenerates it from the
reference dataset.

## Frontend setup

From the repository root, in a second terminal:

~~~powershell
cd frontend
npm.cmd install
Copy-Item .env.example .env
npm.cmd run dev
~~~

Open http://localhost:5173 and select Patient or Doctor. Set VITE_API_BASE_URL
in frontend/.env if the API is not at http://127.0.0.1:8000.
The default backend CORS configuration allows the local frontend on port 5173.

## Verification

Backend, from backend:

~~~powershell
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest -q
~~~

Frontend, from frontend:

~~~powershell
npm.cmd run build
npm.cmd run test:e2e
~~~

Playwright uses installed Microsoft Edge in headless mode and starts Vite on
port 5174. Browser fixtures and mocked model tests verify application behavior;
they do not establish live transcription or multilingual clinical accuracy.
See the progress documents for recorded test results and manual validation gaps.

## Current limitations

- Patient authentication uses phone/password with no OTP verification. Doctor
  identification is phone-only with no session token; production authentication
  and authorization remain unfinished.
- Multilingual symptom classification, transcript accuracy, translation fidelity
  and SOAP section placement require representative evaluation and doctor review.
- Transcript display is off by default. Enabling it does not recover transcripts
  omitted from previously signed snapshots.
- The application does not persist raw audio. Failed uploads can be retried while
  the recording remains in the browser tab; provider retention is separate.
- Front-desk assignment UI, pharmacy and notification flows remain future work.
  No Docker setup is included.
