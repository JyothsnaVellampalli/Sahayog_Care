# Data Stores

Two persistent stores, both read directly against the live project while
writing this document (read-only queries — `information_schema`/`pg_proc`
introspection on Supabase, `list_objects_v2` on S3 — not from migration
files alone, so this reflects what's actually there today, not just what
the SQL *should* have created).

1. **Supabase Postgres** — all relational data, plus the LangGraph
   checkpoint tables (Phase 5/6.3).
2. **AWS S3** (bucket `S3_BUCKET`, region `AWS_REGION`, optional
   `S3_PREFIX`) — transcripts, recordings, SOAP drafts, signed
   consultation records and uploaded reports. Falls back to the local
   filesystem (`backend/storage/`, same key layout) when
   `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`S3_BUCKET` aren't all set —
   see `backend/app/storage.py`.

Row/object counts below are a snapshot taken 2026-11-03 and will drift;
they're included to show relative usage, not as a live dashboard.

## Supabase Postgres

### Catalogue and scheduling

**`specialties`** (8 rows) — specialty catalogue.
| column | type | notes |
|---|---|---|
| id | uuid pk | |
| code | text, unique | e.g. `CARD`, `ORTH`, `DERM`, `GAST` (MVP booking restricts to these four) |
| name | text | |
| description | text, nullable | |
| created_at | timestamptz | |

**`hospitals`** (28 rows) — synthetic hospital/clinic tree used for seeding doctor locations.
| column | type | notes |
|---|---|---|
| id | uuid pk | |
| code | text, unique | |
| name | text | |
| facility_type | text | check `HOSPITAL` \| `CLINIC` |
| city | text | check `Pune` \| `Hyderabad` |
| parent_hospital_id | uuid, nullable, fk→hospitals | clinics point at a parent hospital |
| is_synthetic | boolean | always true today — no real-hospital onboarding flow exists |
| created_at | timestamptz | |

**`doctors`** (40 rows) — doctor identity and auth linkage.
| column | type | notes |
|---|---|---|
| id | uuid pk | |
| doctor_code | text, unique | |
| full_name | text | |
| specialty_id | uuid, fk→specialties | |
| facility_id | uuid, fk→hospitals | |
| languages | text[] | default `['English']` |
| years_experience | integer | check ≥ 0 |
| is_active, is_synthetic | boolean | |
| phone | text, unique, nullable | |
| email | text, nullable | |
| auth_user_id | uuid, nullable | Supabase Auth user id |
| signature_key | text, nullable | **S3 key** — see `signatures/` below |
| signature_uploaded_at | timestamptz, nullable | |

**`doctor_availability`** (0 rows) — recurring/one-off rules used to generate `slots`.
| column | type | notes |
|---|---|---|
| id | uuid pk | |
| doctor_id | uuid, fk→doctors | |
| weekday | smallint, nullable | 0–6, for recurring rules |
| on_date | date, nullable | for one-off overrides |
| start_time / end_time | time | checked `start_time < end_time` |
| slot_minutes | integer | default 45, check > 0 |
| is_active | boolean | |

Unique constraints prevent a duplicate weekly rule or duplicate date
override per doctor. Zero rows currently — slots in the live project were
seeded directly, bypassing this rule table.

**`slots`** (2,843 rows) — bookable appointment slots.
| column | type | notes |
|---|---|---|
| id | uuid pk | |
| doctor_id | uuid, fk→doctors | |
| availability_id | uuid, nullable, fk→doctor_availability | |
| starts_at / ends_at | timestamptz | checked `starts_at < ends_at` |
| status | text | check `OPEN` \| `BOOKED` \| `BLOCKED` |

`unique(doctor_id, starts_at)` prevents double-booking the same doctor at
the same instant.

### Patients and booking

**`patients`** (15 rows)
| column | type | notes |
|---|---|---|
| id | uuid pk | |
| phone | text, unique, nullable | |
| full_name, email | text, nullable | |
| date_of_birth | date, nullable | |
| age | smallint, nullable | checked range |
| gender | text, nullable | checked enum |
| city | text, nullable | checked enum |
| auth_user_id | uuid, nullable | Supabase Auth user id |
| role | text | default `'patient'`, check `patient`\|`doctor`\|`front_desk`\|`admin` — despite the name, this table backs auth-role lookups more broadly than "patients" alone |
| created_at | timestamptz | |

**`emergency_intakes`** (0 rows) — emergency-triage cases that bypass normal slot booking until staff act.
| column | type | notes |
|---|---|---|
| id | uuid pk | |
| patient_id | uuid, nullable, fk→patients | |
| symptoms | jsonb | array of symptom labels |
| deidentified_text | text, nullable | **de-identified** free text (never raw PII) — this is the text Phase 6.1 search-ingests |
| category | text | default `'Emergency'` |
| scores | jsonb | triage scoring detail |
| specialty | jsonb, nullable | resolved specialty suggestion |
| is_met, met_at | boolean / timestamptz | whether staff addressed it |
| linked_appointment_id | uuid, nullable, fk→appointments | once converted to a real appointment |
| created_at | timestamptz | |

**`appointments`** (47 rows) — the single unified visit record: booking → consultation → signed.
| column | type | notes |
|---|---|---|
| id | uuid pk | |
| slot_id | uuid, fk→slots | |
| patient_id | uuid, fk→patients | |
| status | text | check `BOOKED`\|`IN_PROGRESS`\|`CANCELLED`\|`COMPLETED`\|`NO_SHOW` |
| idempotency_key | text, unique | de-dupes retried booking calls |
| reason, severity | text, nullable | |
| symptoms | jsonb | array of `{label}` |
| symptom_text | text, nullable | de-identified free text (renamed from `history` in `phase_3.sql`) — search-ingested as a `symptom` chunk |
| specialty_id | uuid, nullable, fk→specialties | |
| consent_recorded | boolean | consultation-recording consent |
| transcript_key | text, nullable | **S3 key** → raw/edited transcript JSON |
| soap_draft_key | text, nullable | **S3 key** → latest SOAP draft JSON |
| finalised_record_key | text, nullable | **S3 key** → signed consultation record JSON |
| started_at, completed_at | timestamptz, nullable | |
| emergency_intake_id | uuid, nullable, unique, fk→emergency_intakes | |
| linked_appointment_id | uuid, nullable, fk→appointments (self) | follow-up chaining |
| created_at | timestamptz | |

Columns `legacy_consultation_id`, `allergies`, `vitals` existed in an
earlier shape and were dropped by `phase_3.sql` — they are **not** in the
live table; don't go looking for data there.

RPC `book_appointment(...)` is a thin wrapper (adds follow-up linking) over
`book_appointment_base` — `phase_6_followups_reports.sql` renamed the
original `phase_3.sql` function to `_base` and gave the public name to a
new wrapper. `guard_followup_link()` (trigger) enforces follow-up rules
(same patient, prior visit must be `COMPLETED`, no cycles) on both
`appointments` and `emergency_intakes`. `reschedule_appointment(patient_id,
appointment_id, slot_id)` atomically moves a `BOOKED` appointment to a
different `OPEN` slot of the same doctor, re-opening the old one — see
"Not tracked in migrations" below.

### Consultation processing (Phase 5)

**`consultation_jobs`** (10 rows) — background transcription/SOAP job queue.
| column | type | notes |
|---|---|---|
| id | uuid pk | |
| appointment_id | uuid, fk→appointments | |
| kind | text | check `TRANSCRIPTION`\|`SOAP` |
| dedupe_key | text | |
| state | text | check `QUEUED`\|`RUNNING`\|`SUCCEEDED`\|`FAILED` |
| payload | jsonb | job input (segment ids, force-flag, etc.) |
| result_key | text, nullable | **S3 key** → job result JSON |
| source_hash | text, nullable | hash of input, to skip re-processing unchanged input |
| error | text, nullable | |
| attempts | integer | capped at 3 (`consultation_retry_limit.sql`) |
| lease_token, lease_until | uuid / timestamptz, nullable | claim/lease concurrency control |
| created_at, updated_at | timestamptz | |

`unique(appointment_id, kind, dedupe_key)`. RPCs: `enqueue_consultation_job`
(also returns `superseded_soap_job_id` — a forced regenerate supersedes a
stuck SOAP job rather than queuing alongside it), `claim_consultation_job`,
`finish_consultation_job`, `retry_consultation_job`, `save_consultation_draft`;
trigger `guard_consultation_processing` blocks job mutation outside an
open, consented consultation. `purge_stale_consultation_jobs(ttl_days=15)`
deletes terminal rows past TTL and returns their storage keys for cleanup
(invoked by a maintenance script, not automatically).

**`consultation_recordings`** (3 rows) — permanent audio-provider state, independent of job-row TTL.
| column | type | notes |
|---|---|---|
| appointment_id, recording_id | uuid | composite pk |
| provider_state | jsonb | Sarvam transcription-provider session state |
| audio_key | text, nullable | **S3 key** → raw audio file |
| updated_at | timestamptz | |

RPC `save_consultation_recording_audio`. Kept forever as proof of the
original recording, by design — not subject to the job-TTL purge above.

### Prescriptions

**`consultation_prescriptions`** (47 rows) — one row per appointment, replacing the old S3-JSON prescription files (see Stale candidates).
| column | type | notes |
|---|---|---|
| appointment_id | uuid pk, fk→appointments | |
| doctor_id | uuid, nullable, fk→doctors | |
| active | boolean | default true |
| soap_revision | text, nullable | hash tying the prescription to a specific SOAP version |
| soap_draft_key | text, nullable | |
| reviewed_at, updated_at | timestamptz | |

**`consultation_prescription_items`** (54 rows) — line items.
| column | type | notes |
|---|---|---|
| appointment_id, brand_id | fk composite pk | fk→consultation_prescriptions, fk→pharmacy_brands |
| medicine_id | text, fk→pharmacy_medicines | |
| position | integer | display order |
| quantity | integer, nullable | check ≥ 0 when set |
| strength_form, dose, frequency, duration, instructions | text | default `''` |
| details | jsonb | default `{}` |

RPCs `read_consultation_prescription` / `write_consultation_prescription`.

### Pharmacy

**`pharmacists`** (1 row), **`helpdesk_staff`** (1 row) — staff identity, `phone unique`, `is_active`.

**`pharmacy_medicines`** (90 rows) — generic drug catalogue.
| column | type | notes |
|---|---|---|
| id | text pk | |
| generic_name | text | |
| specialty | text | check `cardiology`\|`orthopedics`\|`dermatology`\|`gastroenterology` |
| composition | text | |
| source_details | jsonb | provenance of the catalogue entry |

**`pharmacy_brands`** (166 rows) — purchasable brand/variant with live stock.
| column | type | notes |
|---|---|---|
| brand_id | text pk | |
| medicine_id | text, fk→pharmacy_medicines | |
| brand, manufacturer, variant | text | |
| source_status | text | check `web_confirmed`\|`unverified` |
| stock_quantity | integer, nullable | checked ≥ 0 |
| stock_is_demo | boolean | default true — demo stock, not real inventory |
| locked_quantity | integer | default 0, reserved-but-not-dispensed |
| available_quantity | integer, generated | `stock_quantity - locked_quantity` |
| stock_updated_at | timestamptz, nullable | |

**`pharmacy_reservations`** (4 rows) — stock locked at prescription time, released/dispensed later.
| column | type | notes |
|---|---|---|
| appointment_id, brand_id | fk composite pk | |
| medicine_id | text | backfilled from `brand_id` by trigger `set_reservation_medicine` |
| quantity | integer | check > 0 |
| status | text | check `LOCKED`\|`RELEASED`\|`DISPENSED` |
| created_at, resolved_at | timestamptz | |
| resolved_by | uuid, nullable, fk→pharmacists | |

RPC `finalize_consultation_with_stock` is a validating public wrapper over
`finalize_consultation_stock_internal` (the original body, renamed when the
wrapper was added) — it signs the consultation and locks pharmacy stock in
one transaction. `resolve_pharmacy_reservation` releases or dispenses a
reservation.

### Helpdesk, reports and follow-ups

**`consultation_reports`** (18 rows) — uploaded report metadata; the file itself lives in S3.
| column | type | notes |
|---|---|---|
| id | uuid pk | |
| appointment_id | uuid, fk→appointments | |
| report_type | text | |
| title | text | |
| findings | jsonb | structured/extracted findings |
| object_key | text | **S3 key** → the PDF/image itself |
| content_type | text, nullable | |
| size_bytes | integer, nullable | |
| reported_at | timestamptz | |
| is_synthetic | boolean | default false — true for seeded demo reports |
| uploaded_by | uuid, nullable | |
| uploaded_role | text, nullable | who uploaded (doctor/helpdesk/patient) |

### Search ingestion (Phase 6.1 — patient chatbot foundation)

**`search_ingestion_jobs`** (123 rows) — decoupled job queue feeding the OpenSearch index.
| column | type | notes |
|---|---|---|
| id | uuid pk | |
| kind | text | check `APPOINTMENT`\|`EMERGENCY_INTAKE`\|`CONSULTATION_SIGNED`\|`REPORT` |
| source_id | uuid | the appointment/intake/report id being chunked |
| state | text | check `QUEUED`\|`RUNNING`\|`SUCCEEDED`\|`FAILED` |
| payload | jsonb | |
| chunk_count | integer, nullable | how many chunks this job produced |
| error | text, nullable | |
| attempts | integer | capped at 3 |
| lease_token, lease_until | uuid / timestamptz, nullable | |
| created_at, updated_at | timestamptz | |

`unique(kind, source_id)` — re-enqueuing the same source is a no-op.
RPCs: `enqueue_search_job`, `claim_search_job`, `finish_search_job`,
`fail_search_job`, `retry_search_job`. Deliberately **without** the
`guard_consultation_processing`-style consent guard, since ingestion fires
at booking/signing/report-upload time, not only during an open consultation.

The actual chunk text + embeddings do **not** live in Postgres — they're
written to the AWS OpenSearch index (`OPENSEARCH_INDEX`), documented in
[Phase 6 progress](Progress/Phase6.md), not here.

### LangGraph checkpoint tables (Phase 5 / 6.3 — not app migrations)

`checkpoints` (136 rows), `checkpoint_blobs` (78 rows), `checkpoint_writes`
(327 rows), `checkpoint_migrations` (10 rows) — created by
`PostgresSaver.setup()` (the `langgraph-checkpoint-postgres` package) the
first time the SOAP graph or chat agent connects, **not** by anything in
`backend/database/`. They store serialized LangGraph state
(`checkpoints.checkpoint` jsonb, `checkpoint_blobs.blob` bytea) keyed by
`thread_id` — `soap:<appointment_id>:<job_id>` for the Phase 5 SOAP graph's
resumability, `chat:<patient_id>` for the Phase 6.3 chat agent's one
continuous conversation thread per patient. Both features degrade to
running without checkpointing (no resumability / no persisted chat
history) if `CONSULTATION_CHECKPOINT_DB_URL` is unset, rather than failing.

### Supabase-platform function

`rls_auto_enable()` is a Supabase-managed event trigger (fires on every
`CREATE TABLE` in `public`, auto-enabling row-level security) — not
application code, not tied to any table above, nothing to maintain here.

## AWS S3 (object storage)

Config: `S3_BUCKET`, `AWS_REGION` (default `ap-south-1`; the live
deployment uses `ap-south-2`), optional `S3_PREFIX`,
`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`. All unset → local filesystem
fallback under `backend/storage/`, same key layout (`backend/app/storage.py`).

| Key pattern | Format | Written by | Read by |
|---|---|---|---|
| `signatures/{doctor_id}.{ext}` | PNG/JPEG | doctor signature upload | consultation signing (fetches the image to embed) |
| `transcripts/{consultation_id}.json` | JSON `{consultation_id, segments}` | manual transcript save/edit | transcript load; SOAP job fallback when `appointments.transcript_key` is unset |
| `recordings/{consultation_id}/{recording_id}.{ext}` | raw audio (webm/ogg/m4a/mp4/wav/mp3) | consultation audio upload | kept as permanent proof, not read back programmatically; pointer in `consultation_recordings.audio_key` |
| `transcription_results/{appointment_id}/{job_id}/{lease_token}.json` | JSON transcription-job result | transcription job worker | transcript load, via `consultation_jobs.result_key` |
| `transcript_edits/{visit_id}/{uuid}.json` | JSON `{segments}` | manual transcript edit (post-transcription) | transcript load, via `appointments.transcript_key` |
| `soap_results/{visit_id}/{job_id}/{lease_token}.json` | JSON `{soap, suggestions, source_hash}` | SOAP job worker | SOAP load, via `appointments.soap_draft_key`; prescriptions |
| `soap_results/{consultation_id}/edited-{uuid}.json` | JSON `{soap, suggestions: []}` | manual SOAP edit | same as above |
| `signed_consultations/{visit_id}/{uuid}.json` | JSON `{soap, signature, signed_by, doctor_name, signed_at, ...}` | consultation sign-and-close | signed-record read (helpdesk/patient/doctor views), via `appointments.finalised_record_key` |
| `reports/{appointment_id}/{report_id}.{pdf\|png\|jpg}` | PDF/PNG/JPEG | report upload | report viewer; Phase 6.1 search-ingestion text extraction, via `consultation_reports.object_key` |
| `demo_seed/v1/{appointment_id}/{transcript\|soap\|signed}.json`, `.../report-{n}.pdf` | same JSON/PDF shapes as above | `scripts/seed_demo_patients.py` (one-off demo data) | same readers as above — these are just the literal values stored in `transcript_key`/`soap_draft_key`/`finalised_record_key`/`consultation_reports.object_key` for seeded appointments, not a separate code path |

147 of the 180 live objects are `demo_seed/v1/...` — the bulk of what's in
the bucket today is seeded demo data, not real usage.

## Stale / cleanup candidates

Flagging for your review — not deleting anything.

**S3 prefixes with objects but no current writer** (confirmed by grepping
`app/` for every call site, and cross-checked against what's actually in
the bucket):
- `soap/{consultation_id}.json` — **2 objects live**. The function that
  reads this (`soap.load_draft`) is only a fallback for pre-Phase-5 data;
  nothing writes this key anymore (superseded by `soap_results/...`).
- `transcription_jobs/{consultation_id}/{recording_id}.json` — **2
  objects live**. Explicitly called "legacy" in `transcription.py`'s own
  docstring; read once as a one-time migration into
  `consultation_recordings`, never written to anymore.
- `prescriptions/{appointment_id}.json` — **1 object live**. Read only as
  a legacy-import fallback when `consultation_prescriptions` has no row
  yet (now the real store); no writer exists.
- `prescription_suggestions/{consultation_id}.json` — **1 object live**.
  Read once in `prescriptions.py`; no writer found anywhere in the current
  codebase — looks like a leftover from a removed code path.
- `prescription_workspaces/{appointment_id}.json` — pattern exists in a
  legacy-read fallback but **0 objects in the bucket** — nothing to clean
  up here either way.

These five together are ~6 small JSON objects total — safe to archive or
delete; nothing in the current app reads them except the one-time-import
fallbacks noted above (and `prescription_suggestions`, which nothing reads
at all).

**Supabase table with no migration and no live code reference:**
- `consultations_legacy_archive` — **0 rows**. Not created by any file in
  `backend/database/` (grepped all 19) — it predates this migration set.
  Two maintenance scripts (`phase_3_cleanup.sql`, `reset_booking_data.sql`)
  defensively `DELETE FROM` it *if it exists*, but nothing in `app/`
  selects/inserts into it. Looks like a pre-consolidation leftover, safe
  to drop if you confirm you don't need its history.

**Supabase function with no migration and no live caller:**
- `reschedule_appointment(patient_id, appointment_id, slot_id)` — exists
  live in the database (full working logic — moves a `BOOKED` appointment
  to a different open slot) but isn't created by any tracked migration
  file, and no code in `app/` calls it. Either an abandoned
  patient-reschedule feature or something applied by hand and never wired
  up. Not harmful to leave (no table bloat), but worth knowing it's
  effectively dead code sitting in the database if you're auditing for
  unused surface area.

**Dropped columns, for reference only (not live, nothing to clean up):**
`appointments.legacy_consultation_id`, `appointments.allergies`,
`appointments.vitals` — removed by `phase_3.sql`; mentioned only so you
don't go looking for data in them.
