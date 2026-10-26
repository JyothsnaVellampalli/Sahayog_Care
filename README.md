# Sahayog Care

An AI-assisted patient and doctor platform for a multi-hospital network. See
`docs/PRD.md` for the full product definition and architecture, `docs/Workflow.md`
for the phased build plan, and `docs/Progress/Phase1.md` for what has been built.

## What works today (Phase 1 — patient portal)

- **Landing page** — profile selector (Patient / Doctor / Front desk), Chrome-style.
- **Patient login** — phone + password, backed by Supabase Auth; new numbers
  register with name, age, gender (mandatory), email, and location. (Dev-stage:
  no OTP/phone verification yet; `role` is stored for future authorization.)
- **Book an appointment** — searchable, accessible symptom multi-select plus a
  free-text box. A LangGraph flow:
  1. validates the selection,
  2. **de-identifies** the free text (removes name/phone/email/address/IDs)
     before any model call,
  3. **triages** the condition with the **Jev** decision model
     (Emergency / Severe / Normal / Need more information) by weightage,
  4. **Emergency** → records an `emergency_intakes` row and ends with guidance,
  5. otherwise → **matches a doctor specialty** (Jev), lists doctors with their
     earliest open **slots**, and lets the patient book one (Severe shows
     earliest-slot guidance).
- **My appointments** — merged list of the patient's booked appointments and
  their not-yet-attended emergencies.
- **Observability** — the booking graph is traced in **LangSmith** (each node is
  a span; no PII in traces).

## Tech stack

Python 3.12 · FastAPI · LangGraph · Supabase (Postgres + Auth) ·
OpenRouter (Jev decision model) · React + Vite · LangSmith.

## Project structure

```
Sahayog Care/
├── backend/                     # FastAPI backend (Python 3.12)
│   ├── app/
│   │   ├── main.py              # app + routers (meta, book_appointment, patient)
│   │   ├── config.py            # env-based settings
│   │   ├── book_appointment/    # intake graph, Jev classifier, de-id, db, tracing
│   │   │   └── data/            # symptoms.json + symptom_categories.json (source of truth)
│   │   └── patient/             # login/registration, profile, appointments
│   ├── database/                # setup.sql + migrations (phase_1_4*.sql)
│   ├── scripts/                 # clean_symptoms, seed_slots, apply_migration
│   ├── tests/
│   ├── requirements.txt         # + requirements-dev.txt, requirements-deid.txt
│   └── .env.example
├── frontend/                    # React + Vite
│   └── src/
│       ├── auth/                # patient auth context
│       ├── components/          # accessible SymptomMultiSelect
│       └── pages/patient/       # login, portal, book-appointment, my-appointments
├── References/                  # Symptom-severity.csv, Categorise_symptom.txt
└── docs/                        # PRD, UI design, workflow, progress notes
```

## Prerequisites

- **Python 3.12** (required by `docs/PRD.md` section 7; newer versions lack a
  wheel for a pinned dependency).
- **Node.js 18+** and **npm** (developed against Node 24 / npm 11).
- A **Supabase** project and an **OpenRouter** API key for the live flow.

If Python 3.12 is not installed (Windows):

```powershell
winget install --id Python.Python.3.12 -e --source winget
```

## Backend setup (FastAPI)

```powershell
cd backend

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Configure environment: copy the example and fill in real values.
Copy-Item .env.example .env

# Run the API (http://127.0.0.1:8000)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Verify: health at http://127.0.0.1:8000/health, API docs at http://127.0.0.1:8000/docs.

### Backend environment variables (`backend/.env.example`)

| Variable                     | Purpose                                                    |
| ---------------------------- | ---------------------------------------------------------- |
| `APP_NAME`, `ENVIRONMENT`    | Service metadata.                                          |
| `FRONTEND_ORIGINS`           | JSON array of origins allowed by CORS.                     |
| `SUPABASE_URL`               | Supabase project URL.                                      |
| `SUPABASE_ANON_KEY`          | Supabase anon key (sign-in).                               |
| `SUPABASE_SERVICE_KEY`       | Supabase service-role key (server-side admin / DB writes). |
| `DB_PASSWORD`                | Postgres password (used by migration script).             |
| `OPENROUTER_API_KEY`         | OpenRouter key (used by the Jev classifier).               |
| `SYMPTOM_CLASSIFIER_MODEL`   | Jev model id (default `typesafe/jev-1.13`).                |
| `OPEN_ROUTER_CLASSIFIER_URL` | Jev decisions endpoint.                                    |
| `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`, `OPENROUTER_TIMEOUT_SECONDS` | Chat-model settings (later phases). |
| `LANGSMITH_*`                | Tracing (tracing flag, endpoint, API key, agent id/env).   |

Never commit the real `.env` — only `.env.example` is tracked.

### Database setup (Supabase / Postgres)

Run the SQL in `backend/database/` against your Supabase project (SQL Editor or
`python backend/scripts/apply_migration.py <file.sql>`):

1. `setup.sql` — core tables + seed specialties/hospitals/doctors.
2. `phase_1_4.sql` — patient login/profile columns + appointment `reason`.
3. `phase_1_4_emergency.sql` — the `emergency_intakes` table.

Then seed synthetic appointment slots (the schema seeds no slots):

```powershell
python backend/scripts/seed_slots.py
```

The symptom catalogue is managed as JSON (`app/book_appointment/data/symptoms.json`),
regenerated from the dataset with `python backend/scripts/clean_symptoms.py`.

### Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

## Frontend setup (React + Vite)

```powershell
cd frontend
npm install
Copy-Item .env.example .env   # optional: set VITE_API_BASE_URL
npm run dev                    # http://localhost:5173
```

Other scripts: `npm run build`, `npm run preview`.

| Variable            | Purpose                                      |
| ------------------- | -------------------------------------------- |
| `VITE_API_BASE_URL` | Base URL of the backend API (default 8000).  |

## Running the full stack

Two terminals: backend on 8000, frontend on 5173. The dev-server origin
(`http://localhost:5173`) is already allowed by the backend CORS config. Open the
app, pick **Patient**, sign in / register, and book an appointment.

## Notes

- **Dev-stage auth:** phone + password with no OTP verification yet. The Phone
  provider / SMS integration and real authorization (RLS, role checks) are later
  phases; the `role` column and Supabase Auth user are already in place.
- **Docker:** not included yet (the search engine may run via a managed cloud
  service rather than local Docker).
- See `docs/PRD.md` and `docs/UI_Design.md` for scope and design.
```
