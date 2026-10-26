# Phase 1 — Patient portal — Progress

## Phase 1.1 — Project setup + landing page + FastAPI backend

Status: Complete (pending user confirmation)

### Done When (from docs/Workflow.md) — checklist

- [x] A simple landing page — React app with a profile selector (Patient, Doctor, Front desk), styled like the Chrome "choose a profile" screen per `docs/UI_Design.md`.
- [x] Backend is set up — Python FastAPI backend with `/` and `/health` endpoints, CORS configured for the React dev server.
- [x] Requirements — `backend/requirements.txt` with pinned versions.
- [ ] Docker file — intentionally **skipped** for this phase per the user (exploring Elasticsearch via AWS free trial instead of a local Docker search engine for now).
- Supabase (free tier) — config placeholders wired via environment variables (`SUPABASE_URL`, `SUPABASE_ANON_KEY`); no live project created yet.

### What was built

Repository layout added:

```
Sahayog Care/
├── .gitignore
├── backend/
│   ├── .env.example
│   ├── requirements.txt
│   └── app/
│       ├── __init__.py
│       ├── config.py        # pydantic-settings; reads env, CORS origins, Supabase placeholders
│       └── main.py          # FastAPI app: GET / and GET /health
└── frontend/
    ├── .env.example         # VITE_API_BASE_URL
    ├── index.html
    ├── package.json         # React 18, Vite 6
    ├── vite.config.js        # dev server on port 5173
    └── src/
        ├── App.jsx
        ├── main.jsx
        ├── index.css
        └── pages/
            ├── LandingPage.jsx   # Chrome-style profile selector
            └── LandingPage.css
```

### Backend

- Stack: Python 3.12, FastAPI 0.115.6, Uvicorn, Pydantic v2 (2.10.4), pydantic-settings, python-dotenv — matching PRD section 7.
- `GET /` returns service metadata; `GET /health` returns a liveness payload.
- Configuration is read from environment variables only; `.env.example` is committed, real `.env` is gitignored (PRD section 9: no secrets in the repo).
- CORS allows the React dev server (`http://localhost:5173`).

Run locally:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

### Frontend

- Stack: React 18 + Vite 6 (per PRD: "React js for frontend"; the user chose a React app for the landing page).
- Landing page is a profile selector with three circular avatars — Patient, Doctor, Front desk — and the "Sahayog Care" brand in the top-left, per `docs/UI_Design.md`.
- Selecting a profile updates UI state only. Profile → portal routing (patient portal etc.) is deferred to a later Phase 1.x task, per the UI design doc.

Run locally:

```powershell
cd frontend
npm install
npm run dev     # serves http://localhost:5173
```

### Verification performed

- Backend deps installed cleanly on Python 3.12; `app.main:app` imports with routes `/` and `/health`.
- Backend server smoke-tested live: `/health` returned `{"status":"ok",...}` and `/` returned service metadata.
- Frontend `npm install` succeeded (0 vulnerabilities); `npm run build` succeeded (29 modules transformed).
- Frontend dev server smoke-tested live: `/` returned HTTP 200 with the root div and brand; the landing component served with "Who is using Sahayog Care?".

### Decisions and deviations

- **Python version:** PRD section 7 requires Python 3.12. Only 3.14.x was installed, and the pinned `pydantic-core` has no 3.14 wheel (PyO3 supports up to 3.13), so the build failed on 3.14. Installed Python 3.12.10 via winget and created the backend venv with it. This keeps the project aligned with the PRD and with later version-sensitive libraries (LangGraph, pgvector tooling).
- **Dockerfile skipped:** Per user direction, no Dockerfile this phase. The search engine (likely Elasticsearch) may run via AWS rather than local Docker; revisit when that decision is made.
- **Supabase:** Not provisioned yet. Only env placeholders are in place so the backend can read credentials later without code changes.
- **React scaffolding:** `npm create vite` is interactive in the current version (prompts for a linter), so the frontend files were authored directly instead to keep the setup deterministic.

### Open items / notes for later phases

- Create the Supabase free-tier project and populate `SUPABASE_URL` / `SUPABASE_ANON_KEY`.
- Decide Elasticsearch hosting (AWS free trial vs. local Docker) and add the corresponding config/Dockerfile if needed.
- `docs/Architecture.md` is currently empty; architecture is sourced from PRD section 7. Consider filling it or pointing it at the PRD.
- Wire profile selection to real portal routes once the patient portal (and others) are built.


---

## Phase 1.2 — Book-an-appointment: symptom intake + condition classifier

Status: Complete (pending user confirmation)

### Done When (from docs/Workflow.md) — checklist

- [x] Patient can select symptoms — multi-select dropdown in the patient portal, backed by the 130-symptom catalogue.
- [x] Patient can add natural-language text — free-text box on the form.
- [x] The system categorises the condition — LangGraph flow de-identifies the text, then the Jev decisions model returns a weightage per category and we pick the highest (Emergency / Severe / Normal / Need more information).

### What was built

Backend `book_appointment` module (`backend/app/book_appointment/`):

- `data/symptoms.json` — 130 cleaned symptoms with stable IDs (S001…S130) and severity weights, generated from `References/Symptom-severity.csv` by `scripts/clean_symptoms.py`. Excludes `extra_marital_contacts` (PRD section 14) and the dataset's `prognosis` artefact.
- `data/symptom_categories.json` — the Emergency / Severe / Normal buckets used by the prompt, kept in a separate editable file (per the goal). Status `DRAFT_PENDING_CLINICIAN`.
- `deidentify.py` — removes direct identifiers (name, incl. titled names like "Dr. X", phone, email, URL, Aadhaar, ABHA, PAN, pincode, address) before any model call. Returns a type→count summary only, never raw values (PRD section 9). Optional Presidio backing if installed.
- `model_adapter.py` — single swappable model adapter (PRD section 7). Its `choice_decision()` calls the **Jev decisions endpoint** (`/api/alpha/decisions`) with the same OpenRouter key and returns a typed decision (chosen option + per-option probabilities). A `classify_json()` chat path is kept for later phases.
- `prompt.py` — builds the Jev `state` (triage rules from `References/Categorise_symptom.txt` + category buckets + allowed symptom list + the patient's de-identified input) and the single Choice `question` whose criteria are the four categories.
- `classifier.py` — calls the adapter's Choice decision and picks the category with the **highest weightage**; validates the result against a Pydantic schema. No natural-language reasoning.
- `graph.py` — the LangGraph: `validate_input → deidentify → classify`. The de-identify node runs before the model call, enforcing the PRD ordering.
- `router.py` — `GET /api/symptoms` and `POST /api/appointments/intake`.

Symptom storage:

- The symptom catalogue is managed in `symptoms.json` only. Per decision, it is NOT stored in the database; it is English-only. The JSON is the single source of truth and may later be hosted in S3 (only the loader in `catalogue.py` would change). The earlier `symptoms.sql` table and Supabase loader script were removed.

Frontend (`frontend/src/`):

- `pages/patient/PatientPortal.jsx` — portal shell with the header (brand left, patient name right) and nav (Book an appointment [default], My appointments).
- `pages/patient/BookAppointment.jsx` — the symptom form: multi-select dropdown → per-symptom rows (severity, duration, remove) → optional age/sex → free-text box → submit shows the category badge plus the per-category weightage bars, and a privacy note when identifiers were removed. (No patient follow-up prompts — this stage only flags urgency.)
- `pages/patient/MyAppointments.jsx` — placeholder table per the UI design (data lands in a later phase).
- `App.jsx` / `LandingPage.jsx` — selecting the Patient profile opens the portal.

### Verification performed

- Unit/regression tests: `backend/tests/` — 10 tests, all passing. They cover de-identification (including the titled-name regression), that PII is removed before the model call, that the highest weightage becomes the category, that the top score wins even if it differs from Jev's raw choice, graceful degradation with no API key, and the "Need more information" category.
- Live API: `GET /api/symptoms` returned all 130 symptoms; `POST /api/appointments/intake` de-identified name/address/pincode/email and returned a structured result.
- Live full stack: frontend served at `http://localhost:5173`; backend responded to the cross-origin API call with the correct `Access-Control-Allow-Origin` header.
- Live Jev decisions run (`typesafe/jev-1.13`): Emergency (chest pain + "cannot breathe" → 1.0), Severe (high fever + vomiting, age 72 → 1.0), and Normal (mild runny nose → 1.0), each returning per-category weightage + confidence with no reasoning text, and PII scrubbed before the call.

### Decisions and deviations

- **Category naming:** The workflow text says "Emergency, Critical, Normal", but the authoritative reference (`References/Categorise_symptom.txt`, which the prompt must use) defines **Emergency, Severe, Normal**. The implementation follows the reference. If you prefer "Critical", it is a one-word change in the reference, the category JSON, the schema, and the UI badge map.
- **Jev decisions model (not a chat LLM):** Categorisation uses the Jev "System One" decision model via OpenRouter's `/api/alpha/decisions` endpoint (`SYMPTOM_CLASSIFIER_MODEL=typesafe/jev-1.13`, `OPEN_ROUTER_CLASSIFIER_URL`). Jev returns a typed decision with a probability (weightage) per category and **no reasoning text**. We send a Choice question over the four categories and pick the highest weightage. This fits the stage's goal of flagging emergencies.
  - Request: `POST {OPEN_ROUTER_CLASSIFIER_URL}` with `{model, state, questions}`; same OpenRouter key.
  - Response: `{"answers": {"triage_category": {"choice", "probabilities", "confidence"}}, "usage": {...}}` — the answer is nested under `answers`.
  - A previous iteration used a chat model (`google/gemini-3.8-flash`); that chat path remains in the adapter (`classify_json`) for later phases but is no longer used for triage.
- **No patient interaction at this stage:** the classifier only scores urgency; there is no "please add more info" back-and-forth. `status` is `OK` (scored) or `UNAVAILABLE` (classifier could not run).
- **Symptoms are JSON-only:** No database table for symptoms. English-only. The JSON will move to S3 later for security.
- **pydantic bump:** 2.10.4 → 2.11.10, required by the Supabase client (`realtime` needs `>=2.11.7`). Phase 1.1 still builds and runs on 2.11.10.
- **Presidio optional:** De-identification uses a built-in regex scrubber by default; Presidio is an optional enhancement (`backend/requirements-deid.txt`) to keep installs reliable on Windows.
- **Emergency hand-off:** Routing an Emergency result to a clinician is deferred to a later phase, as you noted.

### To run the live classifier

1. Set `OPENROUTER_API_KEY` in `backend/.env`. The Jev model/endpoint default to `typesafe/jev-1.13` and `https://openrouter.ai/api/alpha/decisions` (override with `SYMPTOM_CLASSIFIER_MODEL` / `OPEN_ROUTER_CLASSIFIER_URL`).
2. Start the backend (`uvicorn app.main:app --reload`) and the frontend (`npm run dev`), open the Patient profile, and submit the symptom form.

### Open items / notes for later phases

- The symptom catalogue is served from `symptoms.json`; move it to S3 when ready (change only the loader in `catalogue.py`).
- A clinician must review and approve `symptom_categories.json` (currently `DRAFT_PENDING_CLINICIAN`).
- Persist intake submissions and actual appointments; wire "My appointments" to real data.
- Add the emergency hand-off node to the graph.


---

## Phase 1.2 — Enhancements (router, accessible multi-select, a11y, tracing)

Status: Complete (pending user confirmation)

### 1. LangSmith tracing (observability / audit)

- Added `langsmith==0.14.12`. `app/book_appointment/tracing.py` exports the `LANGSMITH_*` / `LANGCHAIN_*` env vars (from settings) so LangGraph auto-traces, defines the project `sahayog-care-book-appointment`, and builds a run config (`run_name="book_appointment_intake"`, tags, safe metadata).
- `graph.py` initialises tracing at import and passes the run config into every `invoke`.
- Each graph node appears as its own span: `validate_input`, `deidentify`, `classify`, under the `book_appointment_intake` parent — clear flow for debugging and audit.
- No PII in traces: the free text is de-identified before the classify node, and the removed-identifier summary is type→count only (PRD section 9).
- Config: `LANGSMITH_TRACING`, `LANGSMITH_ENDPOINT`, `LANGSMITH_API_KEY`, `LANGSMITH_AGENT_ID`, `LANGSMITH_AGENT_ENVIRONMENT` (see `backend/.env.example`). Verified live — runs appear in the project with the node spans.

### 2. React Router

- Added `react-router-dom`; `main.jsx` wraps the app in `BrowserRouter`.
- Routes:
  - `/` — landing (profile selector)
  - `/patient` — patient portal layout (redirects to `book-appointment`)
  - `/patient/book-appointment` — symptom intake (default)
  - `/patient/my-appointments` — appointments list
  - `*` — a 404 page
- The portal is a layout route (shared header + nav + `<Outlet />`); nav uses `NavLink` so the active item reflects the URL. Deep links verified (all serve the app).

### 3. Accessible searchable multi-select (symptoms)

- New `components/SymptomMultiSelect.jsx` follows the WAI-ARIA editable-combobox-with-listbox pattern:
  - type-to-search filter; keyboard support (Arrow Up/Down, Home/End, Enter to add, Escape to close, Backspace removes the last chip);
  - `role="combobox"` input with `aria-expanded`, `aria-controls`, `aria-activedescendant`, `aria-autocomplete="list"`; popup `role="listbox"`; rows `role="option"`;
  - selected symptoms shown as removable **chips** above the input, visually separate from the options;
  - distinct hover and keyboard-active highlight; a visually-hidden live region announces the selection count;
  - closes on outside click.

### 4. Accessibility pass (site-wide)

- Skip link to main content; visible `:focus-visible` outlines; `prefers-reduced-motion` support.
- Landing: disabled Doctor / Front desk profiles marked "coming soon" with `aria-describedby`.
- Intake form: fieldset/legend grouping for each symptom's detail and for the "About you" fields; `aria-label`s tying severity/duration to the symptom name; loading `role="status"`, errors `role="alert"`; result region is a labelled `<section>` with an "Assessment" heading and per-category `aria-label`s (visual bars are `aria-hidden`).
- My appointments: table has an off-screen `<caption>` and `scope="col"` headers.
- `index.html` has `lang`, title, and a meta description.
- Note on standards: this implements the WAI-ARIA patterns and WCAG AA practices (contrast, keyboard, names/roles). Full WCAG conformance still needs manual testing with assistive technologies and expert review.

### Verification

- 10 backend tests pass. Frontend builds clean (51 modules).
- Live: SPA deep links serve; `/api/appointments/intake` classifies (Emergency, PII scrubbed, `typesafe/jev-1.13`); LangSmith received the run with all node spans.


---

## Phase 1.3 — Emergency branch + specialty match + doctor/slot booking

Status: Complete (pending user confirmation)

### Done When (from docs/Workflow.md) — checklist

- [x] The graph branches on the emergency check.
- [x] Emergency → the graph ends after logging "An emergency condition. Will handle this condition in this application in later phases."
- [x] Non-emergency → the doctor specialty is identified with the Jev model (scores per specialty), specialties fed from the database.
- [x] Doctors in that specialty are looked up and their available slots listed.
- [x] Severe → the patient sees "Your condition is severe, choose some slot as earliest possible." The slot engine is pure backend logic (no AI).
- [x] A non-emergency patient can select a doctor and a slot.

### What was built

Graph (`graph.py`) — the flow now branches after `classify`:

```
validate_input → deidentify → classify → (conditional)
    Emergency     → emergency (log) → END
    UNAVAILABLE   → END
    otherwise     → match_specialty → find_doctors → END
```

- `emergency` node logs the fixed message and ends (hand-off to a person comes later).
- `match_specialty` loads specialties from the DB and runs a Jev **Choice** decision (one score per specialty); the highest wins. Falls back to General Medicine framing in the instructions.
- `find_doctors` is pure logic: it pulls doctors in the matched specialty and their earliest OPEN slots from the DB. For a Severe condition it attaches the earliest-slot guidance.

Database:

- `backend/scripts/seed_slots.py` — seeds synthetic OPEN slots (the schema had none). Generates slots for each active doctor across the next clinic days (Mon–Sat, 09:00–17:00 IST, 45-min). Idempotent.
- `app/book_appointment/db.py` — read helpers (`list_specialties`, `doctors_by_specialty`, `open_slots_for_doctors`, `doctors_with_slots`) and `book_slot`, which flips a slot OPEN → BOOKED with a guard (`status = 'OPEN'`) so it cannot be double-booked.

API (`router.py`):

- `POST /api/appointments/book` — reserve a chosen slot. Returns whether it succeeded and why not (e.g. already taken).
- `POST /api/appointments/intake` now returns `outcome` (`emergency` / `booking` / `unavailable`), plus `emergency_message`, `severe_guidance`, the matched `specialty` (with scores), and `doctors` (each with their open slots).

Frontend (`BookAppointment.jsx`):

- Emergency → shows the fixed message (no booking UI).
- Non-emergency → shows the suggested specialty, the Severe guidance when applicable, and a list of doctors with selectable slot buttons. Selecting a slot books it and shows a reserved confirmation. Slot buttons have accessible labels ("Book <time> with <doctor>").

### Verification

- 11 backend tests pass (DB-isolated via monkeypatch), covering the emergency branch, the non-emergency specialty + doctors + slots path, and the Severe guidance.
- Live end-to-end: chest pain → Emergency (logged, no doctors); itchy skin rash → Dermatology with 5 doctors and slots; booking a slot flipped it to BOOKED; re-booking the same slot was correctly refused ("Slot is no longer available").

### Decisions and deviations

- **Slots were seeded.** The schema seeds specialties/hospitals/doctors but no slots, so the booking flow had nothing to offer. I added a synthetic slot seeder (PRD section 10: all dev data is synthetic). Run it with `python backend/scripts/seed_slots.py`.
- **Booking depth.** "Select doctor and slot" is implemented as reserving the slot (OPEN → BOOKED) with a double-book guard. A full appointment record (with patient identity, idempotency key, audit event) is deferred, since patient identity/records are not part of this phase.
- **Removed stray debug prints.** `classifier.classify` had `print()` statements dumping the full prompt to the console on every request; these were removed.
- **Specialty via Jev scores** mirrors the triage decision (same Choice pattern), with the specialty list and descriptions fed from the database as the options.

### Open items / notes for later phases

- Emergency hand-off to a named person.
- Full appointment records + patient identity + audit events on booking.
- Doctor availability generation from `doctor_availability` rather than a flat seeder.


---

## Phase 1.4 — Patient login + profile-driven intake + appointments list

Status: Complete (pending user confirmation)

### Done When (from docs/Workflow.md) — checklist

- [x] Patient logs in and adds their details; those details are used for model decisions.
- [x] Patient sees all their previous appointments.

### Auth design (dev stage)

- **Login = phone + password** (no OTP). Supabase Auth backs it, but via **email + password** under the hood, because the project's Phone provider is disabled (enabling true phone/OTP needs an SMS provider). The patient only ever enters their phone and password; the email is collected on the signup details screen and used to create the Supabase Auth user.
- The `patients` profile row links to the Supabase Auth user (`auth_user_id`) and stores `role` (default `patient`) for **future role-based authorization**. The session returned is a real Supabase Auth JWT.
- This is explicitly a dev-stage shortcut: phone-number verification is skipped. The upgrade path is to enable the Phone provider + an SMS provider and switch login to OTP.

### Flow

1. Landing → Patient → `/patient/login`.
2. Patient enters **phone + password**. Backend looks the phone up:
   - **Exists** → sign in with the stored email + password → session + profile.
   - **New** → details screen asks **name, age, gender (mandatory), email, location (Pune/Hyderabad)** → create Supabase Auth user + profile → sign in.
3. The portal is guarded: unauthenticated users are redirected to the login screen.

### What was built

Database migration (`backend/database/phase_1_4.sql`, applied via `scripts/apply_migration.py`):

- `patients`: added `phone` (unique), `full_name`, `email`, `age`, `auth_user_id`, `role` (check: patient/doctor/front_desk/admin) + indexes.
- `appointments`: added `reason` (the human-readable summary shown in the list, e.g. "Orthopaedics - Severe").

Backend (`app/patient/`):

- `service.py` — `get_patient_by_phone` / `get_patient_by_id`, `login`, `register` (creates the Auth user with `email_confirm=true`, inserts the profile, rolls back the Auth user if the insert fails), `list_appointments` (joins slots → doctors → specialties), `create_appointment`.
- `router.py` — `POST /api/patients/lookup`, `/login`, `/register`, and `GET /api/patients/{id}/appointments`.
- Booking (`/api/appointments/book`) now accepts `patient_id` + `reason` and creates an `appointments` row so the booking appears in "My appointments".
- Intake (`/api/appointments/intake`) accepts `patient_id`; the graph's `validate_input` node reads the patient's **age and gender from the profile** and uses them for the classifier — the form no longer asks for them.

Frontend (`frontend/src/`):

- `auth/PatientAuth.jsx` — auth context, persisted to localStorage so a refresh keeps the session.
- `pages/patient/PatientLogin.jsx` — two-step phone+password → details screen.
- `App.jsx` — `/patient/login` route and a `RequirePatient` guard on the portal.
- `PatientPortal.jsx` — shows the real patient name and a Sign-out button.
- `BookAppointment.jsx` — the "About you" (age/sex) fields were removed; intake and booking send the `patient_id`.
- `MyAppointments.jsx` — fetches and lists the patient's appointments (date, doctor + specialty, reason, status).

### Verification

- 11 backend tests pass.
- Live full stack: a brand-new phone registered (name/age/gender/email/location), logged in, ran intake (age + gender taken from the profile, not the form → matched Orthopaedics for joint pain), booked a slot (appointment persisted), and the booking appeared in "My appointments". Existing-phone login and wrong-password rejection also verified. All SPA routes serve.

### Decisions and deviations

- **Email added to signup** (per the updated direction) so Supabase Auth has a usable identity while phone stays the login key.
- **No phone verification** at this stage (dev), as agreed.
- **Age stored directly** on the profile (the UI asks for age, not date of birth); the legacy `date_of_birth` column is left unused.
- **Location = Pune / Hyderabad** dropdown, matching the existing `city` check constraint and where doctors exist.
- Booking still reserves the slot (OPEN → BOOKED) and now also writes the appointment row linked to the patient.

### Open items / notes for later phases

- Enable the Supabase Phone provider + SMS provider and switch login to OTP (remove the email-backing shortcut).
- Enforce authorization with the JWT/role (RLS policies, role checks) — the `role` column and Auth user are in place for this.
- Cancelling/rescheduling appointments; the appointment detail page from the UI design.


### Phase 1.4 follow-up — emergency intakes + unified "My appointments"

Problem reported: an Emergency case saved nothing, and some patients saw an empty "My appointments" (the intake was only persisted when a slot was booked, and Emergency never books).

Changes:

- **New `emergency_intakes` table** (`backend/database/phase_1_4_emergency.sql`): `patient_id`, `symptoms` (jsonb, readable labels), `deidentified_text`, `category`, `scores` (jsonb), `is_met` (bool, default false), `met_at`, `created_at`. This is also the queue the front-desk section will use later.
- **The graph's `emergency` node now records the case** to `emergency_intakes` (de-identified text only; no raw PII). It no longer just logs and ends.
- **`is_met` flow:** when staff attend to an emergency, they set `is_met = true` and create a normal `appointments` row. So the case lives in exactly one place at a time.
- **"My appointments" is now a merged list:** all of the patient's `appointments` rows **plus** their **not-yet-met** emergencies (`is_met = false`). Once an emergency is met, it drops out of the emergency source (it's now an appointment), so it's never shown twice. Each item is tagged `type` = `appointment` or `emergency`; the UI shows emergencies with a red "Emergency / Awaiting care team" row.
- **Bug fix:** the booking endpoint previously swallowed appointment-insert failures and still reported success (so a booking could silently not appear in the list). It now returns `ok = false` with the reason when the appointment record can't be written.

Verification (live): an Emergency intake for the test patient created an `emergency_intakes` row and appeared in "My appointments" alongside the booked appointment; setting `is_met = true` removed it from the list (no duplication). 11 backend tests pass.

Open items: the front-desk screen to view/attend emergencies (set `is_met` + create the appointment) is a later phase.
