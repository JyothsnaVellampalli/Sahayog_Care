# Phase 5 - Memory - Progress

Status: Complete.

### Done When - checklist

- [x] Setup langraph postgres checkpointer for holding the consultation information.
- [x] No information should be lost in any case.

### Context

Workflow.md's Phase 5 goal was a LangGraph `PostgresSaver` checkpointer, because
a doctor may pause/resume speaking mid-visit and SOAP generation may need to
restart. By the time this phase was picked up, the durable job-queue
foundation below (built as the "processing follow-up" after
[Phase 4.2/4.3](Phase4.md#phase-42---doctor-prescriptions-and-soap-layout))
already satisfied most of "no information lost" through a different
mechanism than planned — a leased Supabase job queue, not a LangGraph
checkpointer. This phase's remaining "Delivered" sections cover the four
concrete pieces that were still missing against the original Workflow goal:
permanent audio retention, active SOAP preemption, an optional Postgres
checkpointer for the SOAP graph itself, and TTL-based retention.

### Delivered - durable job queue foundation

- After Stop, the browser uploads the recording and the backend commits a
  durable Supabase job before acknowledging it. The doctor can select and
  edit medicines during transcription and SOAP generation. Once the upload
  is acknowledged, closing the screen does not cancel processing; reopening
  reads job status, transcript, saved SOAP, and the prescription draft from
  their respective stores. The server must remain running; expired job
  leases recover after a restart.
- Transcription completion and the next SOAP job are committed in one
  database transaction. The SOAP worker runs the translation/SOAP graph and
  publishes its result pointer only if it still owns the lease. Model
  processing has a four-minute deadline; failures expose Retry SOAP. If a
  transcript exists without an active job, Generate SOAP is available.
  Reading a consultation never starts a model call.
- Medicine drafts autosave independently of SOAP, including incomplete
  instructions and empty prescriptions. Final review requires the current
  SOAP. Signing checks the saved prescription under the appointment lock,
  then reserves stock and closes the appointment in the existing
  transaction. Closed prescriptions cannot be edited. Reservations include
  both brand and medicine IDs, with a database constraint ensuring the pair
  matches the catalogue. Stock is reserved for the specific brand: available
  quantity excludes locks, dispensing reduces physical stock, and release
  returns availability without changing physical stock.
- Storage model:
  - Supabase `consultation_prescriptions`: appointment, doctor, review/version state.
  - Supabase `consultation_prescription_items`: appointment, medicine and brand
    foreign keys, quantity, strength/form, dose, frequency, duration, instructions
    and display metadata.
  - Supabase `consultation_jobs`: queue, leases and errors.
  - Supabase `consultation_recordings`: Sarvam job ID/upload checkpoint.
  - S3 (or local storage): transcripts, SOAP results, signed clinical/signature
    snapshots. New signed snapshots do not contain prescriptions; doctor,
    patient and pharmacy reads compose the snapshot with the relational
    prescription. Patients still receive signed records only.
  - The old `transcription_jobs/` S3 folder held Sarvam job IDs and upload
    checkpoints, allowing interrupted uploads/polls to resume. New checkpoints
    use Supabase. Legacy checkpoints and pending audio objects remain readable
    so existing work can finish. Appointment/job rows retain object keys to
    retrieve the correct clinical documents.

### Delivered - permanent audio

- Uploaded recordings are written to object storage (`recordings/<appointment-id>/<recording-id>.<ext>`)
  before the transcription job is even enqueued, and are never deleted on
  success — kept indefinitely as proof. Raw audio no longer passes through
  the `consultation_jobs` table as inline base64; the job payload only
  carries the permanent storage key.
- The job's `payload.audio_key` and `consultation_recordings.audio_key` both
  point at the same permanent object; the latter survives job-row TTL
  cleanup (below), so the pointer is never lost even after old job rows are
  purged.

### Delivered - SOAP preemption

- If a doctor resumes speaking while a SOAP job is `RUNNING`,
  `enqueue_consultation_job` immediately flips that SOAP job to `FAILED`
  ("Superseded by a new recording.") instead of letting it finish.
- In the normal single-process deployment, the API request that queued the
  new recording also cancels the matching in-process `asyncio.Task`
  immediately, so the new transcription is claimed right away rather than
  waiting out the SOAP timeout. A fresh SOAP job is still auto-chained once
  the new transcription succeeds, exactly as before.
- The superseded worker's eventual (discarded) publish is rejected by the
  existing lease/state guard in `finish_consultation_job` — no wasted write,
  no duplicate SOAP job. Across multiple processes (no shared event loop),
  the DB-level supersede alone still makes a stale publish impossible; only
  the extra "claimed right away" speed benefit is single-process.
- Known limitation: the translate/SOAP LLM calls run inside a worker thread;
  cancelling the awaiting task stops the queue from waiting on it, but the
  orphaned thread keeps running to completion in the background and its
  result is simply discarded by the DB guard. True mid-HTTP-call abort is
  not implemented — not worth the complexity for a bounded ≤240s call.
- **Regenerate also supersedes.** `enqueue_consultation_job`'s SOAP branch
  used to hand back any already `QUEUED`/`RUNNING` SOAP job unconditionally,
  including a stuck one from an earlier attempt — so clicking "Regenerate
  SOAP" (`{"force": true}`) could silently attach to that old job instead of
  starting a fresh translate+SOAP run, which looked like "nothing happened,
  no translation ran." An explicit forced regenerate now supersedes an
  already-active SOAP job the same way a new recording does; an automatic
  SOAP-after-transcription enqueue (no `force`) still dedupes to the active
  job as before, so it isn't duplicated. See
  `backend/database/consultation_regenerate_fix.sql`.

### Delivered - Postgres checkpointer

- When `CONSULTATION_CHECKPOINT_DB_URL` is set, the SOAP LangGraph compiles
  with a pooled `PostgresSaver` (a connection pool, not a single shared
  connection, since up to two SOAP jobs for different appointments can run
  concurrently in one process), keyed by
  `thread_id = soap:<appointment-id>:<job-id>` (stable across retries of the
  same job row). A crash/restart mid-SOAP-job can resume translation/SOAP
  extraction from the last completed step instead of re-running both LLM
  calls.
- **Safety invariant:** only data already sent to the consultation LLM
  (de-identified turns, their English translation, the SOAP draft) is ever
  placed into checkpointed graph state — raw pre-de-identification transcript
  text is never checkpointed; it stays in the existing `transcripts/<id>.json`
  store and is re-supplied fresh on every attempt.
- Unset, the graph compiles and runs exactly as before Phase 5 (no
  checkpointer, no live dependency at runtime beyond the pinned packages).
  An unreachable configured checkpoint database degrades gracefully: the
  connection attempt is bounded (10s) and the pool is closed on failure
  rather than left retrying in the background indefinitely.

### Delivered - retention (TTL cleanup)

- `consultation_jobs` rows and orphaned per-edit transcript/SOAP draft
  objects (every edit writes a new object; only the appointment's current
  `transcript_key`/`soap_draft_key` is ever read again) are not kept
  forever. `scripts/cleanup_consultation_processing.py` (dry run by default;
  pass `--apply` to delete) purges state older than
  `CONSULTATION_PROCESSING_TTL_DAYS` (default 15).
- It never touches `QUEUED`/`RUNNING` jobs, signed records, signatures, or
  recorded audio — those have no TTL and are kept indefinitely.

### Delivered - retry limit

- `retry_consultation_job` previously reset `attempts` to `0` on every manual
  retry, so a job that keeps failing (e.g. a slow or unreliable configured
  model) could be retried from the UI indefinitely — each retry re-running
  the full translate + SOAP-extraction LLM pipeline from scratch, which is
  exactly what showed up as the same consultation appearing repeatedly in
  LangSmith.
- `attempts` now accumulates across both automatic lease-expiry recovery
  (`claim_consultation_job`, unchanged) and manual retries. Once a job has
  reached 3 attempts, `retry_consultation_job` refuses further retries with
  "This job has failed too many times. Start a new recording or regenerate
  SOAP to try again." — both of which create a fresh job row (and a fresh
  attempt budget), rather than endlessly retrying the same one.
- This does not cap *total* SOAP generations for a visit — Generate/Regenerate
  SOAP always enqueues a new job row, which is intentional (a changed
  transcript should always get a fresh attempt). The cap is specifically on
  retrying the *same* already-failed job.

### Delivered - observability (step-by-step logs)

Debugging a live failure in this pipeline surfaced that nothing below
WARNING was ever visible — module loggers existed but nothing configured a
handler/level, so `logger.info(...)` calls were silently dropped.

- `app/logging_config.py`: `configure_logging()` sets the root logger level
  from `LOG_LEVEL` (default `INFO`) and is called first thing in `main.py`,
  before any other module logs. Chatty HTTP client libraries (`httpx`,
  `httpcore`, `supabase`, `postgrest`, `openai`, `botocore`/`boto3`/
  `s3transfer`, `urllib3`, `hpack`, `h11`) are pinned to `WARNING` so their
  own per-request logging (every outgoing Supabase/S3/OpenRouter call) no
  longer drowns out the app's own progress lines; a real problem from any of
  them (not just a slow poll) still surfaces.
- Booking flow (`book_appointment/graph.py`, `router.py`, `appointments.py`)
  now logs each step: intake started → validate (symptom/invalid counts) →
  de-identify (identifier type counts only) → classify (category, specialty,
  model) → emergency saved/failed → doctors found (specialty, city, count) →
  intake finished → booking result (slot/appointment id).
- Consultation flow (`consultation/service.py`, `router.py`, `jobs.py`,
  `finalization.py`) logs: consultation started, recording upload
  received/queued/(if superseding) cancelled, worker job claimed, job
  succeeded/failed/timed out, SOAP requested/queued, signed and closed.
- The SOAP graph (`soap_graph.py`): every node is wrapped by a `_traced()`
  helper applied at graph-build time, giving a consistent `soap visit=<id>:
  <stage> - starting` / `- done` / `- failed: <reason>` line per stage
  (validating transcript, de-identifying, translating to English,
  generating SOAP, validating SOAP against source, suggesting medicines).
  The underlying LLM call helper (`_call`) additionally logs only the
  underlying exception's *type* (e.g. `APITimeoutError`, `RateLimitError`)
  on failure, never its message — provider SDK error messages can echo back
  request/response bodies, so only the type is safe to log.
- None of this logs symptom text, transcripts or raw model content — only
  IDs, counts and status strings. The one exception is the grounding-check
  warning below, which logs the generated (de-identified, already
  doctor-visible) clinical-note excerpt itself, not raw transcript text.

### Delivered - clinical-note SOAP voice (not a Phase 5 goal, fixed alongside it)

The SOAP extraction prompt and its validation were changed while debugging
this phase; documented in full under
[Phase 2.2 — SOAP](Phase2.md#phase-22---saved-soap-doctor-approval-and-consultation-completion):
`soap_prompt.txt` now asks for third-person clinical-note phrasing (never
"you", never quoted dialogue) instead of verbatim transcript excerpts, and
the grounding check that used to hard-reject low-overlap excerpts (a false
positive on legitimate paraphrasing) is now advisory — it logs a warning
instead of discarding the draft or failing the job, relying on the doctor's
existing mandatory review before signing as the real safety net.

### Setup / deployment

After the existing migrations through Phase 4.3, from `backend`:

```powershell
.venv/Scripts/python.exe scripts/apply_migration.py database/consultation_processing.sql
.venv/Scripts/python.exe scripts/apply_migration.py database/consultation_prescriptions.sql
.venv/Scripts/python.exe scripts/apply_migration.py database/pharmacy_reservation_medicines.sql
.venv/Scripts/python.exe scripts/migrate_consultation_prescriptions.py
.venv/Scripts/python.exe scripts/apply_migration.py database/phase_5_consultation_memory.sql
.venv/Scripts/python.exe scripts/apply_migration.py database/consultation_retry_limit.sql
.venv/Scripts/python.exe scripts/apply_migration.py database/consultation_regenerate_fix.sql
```

Set `LOG_LEVEL=INFO` in `backend/.env` (already the default) to see the new
step-by-step progress logs; no migration is needed for the logging changes.

Imports by the migration script are insert-only and also happen on first
read; originals are retained. Do not reapply `phase_4_3.sql` alone after the
prescription migration because it replaces the signing function; reapply the
prescription migration afterward if needed. `phase_5_consultation_memory.sql`
replaces `enqueue_consultation_job` (preemption-aware) and adds `audio_key` to
`consultation_recordings`, so apply it after `consultation_processing.sql`.

`backend/requirements.txt` now also lists `langgraph-checkpoint-postgres` and
`psycopg`; the SOAP graph only imports them when `CONSULTATION_CHECKPOINT_DB_URL`
is set, and runs without a checkpointer otherwise. Restart/redeploy the API
and frontend with the new code after each migration.

`consultation_regenerate_fix.sql` replaces `enqueue_consultation_job` again:
an explicit forced regenerate now supersedes an already-active SOAP job
instead of silently dedupe-attaching to it; apply after
`phase_5_consultation_memory.sql`.

### Verification

- `scripts/verify_consultation_processing.py` and
  `scripts/verify_stock_transactions.py` use rollback-only database fixtures;
  the former's transaction script also covers: `enqueue_consultation_job`
  superseding a `RUNNING` SOAP job on a new recording; superseding a
  `QUEUED` SOAP job on a forced regenerate while confirming a non-forced
  (automatic) enqueue still dedupes instead of superseding;
  `purge_stale_consultation_jobs` TTL behavior; and the retry-attempt cap
  (a job at 3 attempts cannot be retried again).
- Browser tests in `consultation-processing.spec.js` cover leaving/reopening,
  early medicine entry, and explicit SOAP recovery on mobile and desktop.
- Backend: 159 tests pass, including updated/new coverage in
  `tests/test_consultation_jobs.py` (permanent audio write-before-enqueue,
  in-process task cancellation on a superseding recording, audio retained
  rather than deleted after a successful transcription, the redesigned
  `jobs.process()` timeout path), `tests/test_soap_graph.py` (checkpointed
  state never carries arbitrary payload, only the whitelisted de-identified
  fields) and `tests/test_soap.py` (an unsupported excerpt is flagged via a
  logged warning rather than raising; invalid-schema output still raises).
- Confirmed live against the actual deployed app (not just mocked tests):
  the `PGRST202` missing-function failure before `phase_5_consultation_memory.sql`
  was applied, the slow-translation timeout against a free OpenRouter model,
  the stuck-job regenerate bug before `consultation_regenerate_fix.sql`, and
  the grounding check's false-positive rejection of a legitimately
  rephrased clinical note — each reproduced, diagnosed from the new logs,
  and fixed in this phase.
- Not run in the authoring environment (no live Supabase/Postgres
  available to Claude directly): the actual SQL migrations against a real
  database were applied by the project owner; the extended transaction-SQL
  assertions in `consultation_processing_transaction.sql` describing that
  behavior have not been separately re-run end-to-end since the latest edits.
  Run `verify_consultation_processing.py` against a dev database to confirm.
