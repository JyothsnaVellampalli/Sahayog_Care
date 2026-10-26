## 1. What this project is

Sahyog Care Companion is an AI-assisted patient and doctor platform for a multi-hospital network. It has three functions: finding a doctor and booking a slot, answering patient questions about their own records with cited sources, and turning a consultation into a note that a doctor signs.

Scope, personas, and principles are summarised below. Where this file and an approved ADR disagree, the ADR wins and you flag the difference.

## 2. Goals

1. A patient finds the right doctor and books in under three minutes, without a phone call.
2. A patient sees and questions their own records. Every answer cites its document and page, and only uses that patient's data.
3. A doctor leaves each consultation with a signed note, reviewed in at most 90 seconds.
4. Every AI output is traceable, auditable, and reversible by a named person.
5. The system complies with India's Digital Personal Data Protection Act, 2023, and can be run with identified data kept on-premise.

Board-level measures to report against: share of bookings still made by phone, share of booked patients who do not arrive, volume of scanned report PDFs, and minutes of typing per consultation.

## 3. Scope

In scope: doctor triage and slot booking, record upload, storage and questions, a consultation note assistant with doctor sign-off, and shared services for identity, consent, audit, and evaluation.

Out of scope: billing and insurance adjudication, telemedicine video, wearable data, and inpatient workflows. Do not build these, even if asked in passing. Log the request in `docs/assumptions.md` as a possible extension.

Every feature must serve a named persona. A feature that serves nobody is scope creep.

## 4. Personas

- **Patient (and caregiver):** needs the right specialist quickly, and their reports explained in plain words. Fears their records being read by someone who should not see them.
- **Doctor:** sees about 20 patients a day. Needs a note they can sign in 90 seconds without re-reading the transcript. Fears being on record for a line the model invented.
- **Front desk:** handles about 300 calls a day. Needs fewer calls about which doctor to see. Fears a bot that books the wrong slot.
- **Pharmacist:** needs prescriptions that match stock. Fears substitutions made by software instead of by a pharmacist.
- **Compliance officer:** needs to answer "who saw this record?" with one query. Fears identified health data appearing in a public API log.

## 5. Hard constraints (never violate)

1. Identified health data never leaves India. Store and process it in an India region. Only de-identified text may go to an external language model.
2. The language model vendor must be swappable without rewriting workflows. All model calls go through one adapter.
3. Hospital systems are accessed through read-only FHIR R4 APIs. Never write to them.
4. Pharmacy stock arrives as a nightly CSV today, with an API planned. Stock lookup sits behind one interface with CSV and API adapters.
5. English first. Hindi and Marathi come later. Nothing in the schema may assume English.
6. Peak load is 1,400 requests an hour in the morning. Load-test at this rate before claiming readiness.
7. Retention: audio deleted within 24 hours. Audit records kept one year. Workflow checkpoints kept 30 days, then purged.

## 6. Safety rules (non-negotiable, these override convenience)

1. The emergency check runs before any specialty matching or slot search. Emergency wording ends the flow with fixed emergency guidance and a logged hand-off to a person.
2. Red-flag recall on the emergency evaluation set is 100%, with no exceptions. A failing case blocks release.
3. The system never names a diagnosis, medicine, dose, or prognosis. The model structures what a doctor said. It never prescribes.
4. Nothing from an AI output is saved to a record until a named doctor signs it. An unsigned note is a draft, enforced by schema.
5. Every answer about a record cites its document and page. An answer without a citation is not returned.
6. Scope guard: questions about other patients' records, or asking for a diagnosis or dose, are refused and handed to a doctor.
7. The patient filter is applied in the database query at retrieval, never left to the prompt. Output is also checked for document IDs that belong to someone else.
8. Every record read or write creates an audit event with actor, role, purpose, record, and time.
9. Consent is a stored record (grantee, scope, purpose, expiry), checked on every read. A caregiver sees a record only while consent is valid.
10. Coding assistants never see real identified data. They work on the synthetic layer only.
11. Clinical or financial effects wait for a named person. The workflow pauses. It never guesses.
12. Clinical rules, phrase lists, and fixed message texts change only through a pull request approved by a clinician. Never set a rule's status to approved yourself.

## 7. Architecture

Stack:
- Python 3.12, FastAPI, Pydantic v2. The same models are used at API and data boundaries.
- LangGraph 1.2 for workflows, with `langgraph-checkpoint-postgres` 3.2.x as the checkpointer. Checkpoints are keyed by thread ID. API containers are stateless.
- PostgreSQL with pgvector for relational data, embeddings, and hybrid search.
- Using supabase as database.
- Object store for PDFs and audio. Queue and workers for asynchronous ingest.
- Redis for short-lived operational data, such as slot availability (30 seconds).
- MCP server (`mcp` 2.3.x): optional extension for exposing scheduling and stock as tools.
- Observability: Langfuse 5.x or LangSmith. Every run has a trace ID, printed in every audit event.
- Evaluation: `ragas` 0.4.x for faithfulness and context precision, calibrated against about 20 human-graded samples.
- Privacy: `presidio-analyzer` 2.2.x plus custom recognisers for Indian phone and health ID formats. The token map stays on-premise.
- Speech-to-text: `faster-whisper` 1.2.x, run locally.
- React js for frontend.

Check every version against its current release before pinning, and record the check date in the ADR. Do not rely on versions from memory or from older tutorials.

Workflows:
- **Find my doctor:** intake, emergency check (rules first, language model second), specialty match, shortlist with tools, present options, pause for the patient to pick, book the slot, notify.
- **My records:** the ingest workflow runs on the queue worker. It uploads, parses PDFs (with OCR fallback), tags identifiers, chunks by section, embeds in batches (cached by content hash), indexes, and links to the patient. The question workflow is interactive: take the question and patient ID, apply the scope guard, retrieve with the patient filter, grade the context, answer with citations, run the safety check, then respond or hand off.
- **Consultation note:** transcript, segment speaker turns, draft the note in SOAP format with a JSON schema enforced, extract medicines, check stock (tool call), pause for doctor review, store the signed note and audit event. Nothing is written to the record before the doctor's decision.

Memory has four homes: workflow state (checkpointer, 30 days), long-term patient preferences (until changed), retrieval memory (pgvector chunks, under consent), and operational cache (Redis, 30 seconds).

Guardrails have three layers:
- Input: remove identifiers before any external call, scan for injected instructions, take scope from the authenticated context and never from the prompt.
- Model: constrain output to a schema, forbid diagnosis and dosing in the instructions, allow only the tools each workflow needs.
- Output: check every citation against the retrieved chunks, escalate emergencies, and require a human signature for any clinical act.

Every model call has a schema, a timeout, a fallback, and a trace ID. Every tool call has a timeout, capped exponential backoff, and a circuit breaker.

Writes are idempotent. Clients send an idempotency key. Booking uses unique constraints, so one slot maps to one appointment.

## 8. Repository layout

```           
- docs
```

Keep prompts, schemas, evaluation sets, and decision records as plain versioned text in the repository. Change them only through pull requests.

## 9. Coding standards

General:
- Type-annotate all public functions. Run `mypy --strict` on `services/` and `triage/`.
- Validate every external input with Pydantic at the boundary. Never trust a model's output shape without validation.
- No secrets in code or the repository. Read configuration from environment variables. Commit `.env.example` only.
- Never log raw free text, identifiers, or fields marked SENSITIVE in the symptom catalogue. Log hashes and IDs instead.
- Keep functions small. Put business rules in code and data files, not in prompts.
- No dead code, no commented-out code, and no TODOs without an owner and a ticket reference.

Rules versus code:
- Emergency logic lives in data (`red_flag_rules.csv`, `red_flag_phrases.csv`), not in Python branches.
- The deterministic engine decides emergencies. A language model may add a flag. It may never remove one.
- Emergency and crisis messages are fixed text loaded from files. Never generate them with a model.

Testing:
- Write the evaluation cases before the code. A prompt without a test is a guess.
- Every bug fix adds a regression case to the evaluation set.
- Unit tests run with `pytest`. Evaluation runs are separate and write a timestamped file to `evals/runs/`.
- Coverage target: 90% on `triage/` and `services/agent/guardrails/`. Every public function has at least one test.

Git and pull requests:
- One branch per ticket. Small pull requests, one concern each.
- Prompt, schema, and evaluation-set changes include evaluation results in the pull request.
- Record every significant decision as an ADR in `docs/adr/`: context, three options with costs, the decision, the trigger that would reverse it, and the date checked.
- Never force-push to the main branch. Never commit data without its licence entry in `data/inventory.md`.

Dependencies:
- Pin exact versions in the lock file. Record the check date in the ADR.
- Before adding a library, read its current official docs, changelog, and open issues. Write a minimal reproduction in a scratch file first.

## 10. Data rules

- Public datasets (for example: no-show records, medical transcriptions, the disease-symptom dataset used for the symptom catalogue and severity weights, an Indian medicine dataset) are recorded in `data/inventory.md` with exact row count and licence before use.
- The synthetic layer (doctors, slots, reports, transcripts) is used for development and testing. Every synthetic row carries `synthetic = true`. Synthetic rows are never mixed unlabelled with public rows.
- Every table has a data contract in `docs/data-contracts/`: owner (a role, never a person), schema version, freshness, sensitivity class (direct, quasi, clinical, operational), quality checks, and consumers.
- Sensitivity classes decide what can leave the boundary. Direct identifiers never leave. Quasi-identifiers are generalised. Clinical content is de-identified before any external call.
- Every read or write of any table creates an audit event.

## 11. Evaluation gates

| Metric | Target |
|---|---|
| Triage response time | p95 under 4 s |
| Record question response time | p95 under 8 s |
| Note draft after transcript | p95 under 20 s |
| Availability during clinic hours | 99.5% |
| Bookings completed without a call (synthetic) | at least 70% |
| Median time to book | under 3 min |
| Red-flag recall on emergency set | 100%, no exceptions |
| Specialty accuracy on golden set | at least 85% |
| Answer faithfulness (calibrated judge) | at least 0.9 |
| Scope leaks (red-team set) | zero |
| Doctor review time per note | under 90 s in role-play |
| Cost per consultation | calculated, formula shown |

If a target cannot be met, report the number reached and the reason. Never drop a target from the report.

Evaluation set sizes: at least 30 core cases and 80 extended cases for each of the find-doctor and records workflows. At least 40 extended cases for the note workflow (field-level F1, medicine precision, zero invented medicines). For platform, a load profile and p95 per workflow.

Metrics quoted without a run do not count.

## 12. Definition of done (per ticket)

- Requirement written: what, who it serves, the input it takes, the cost of an error and who would notice, who must sign off, and whether it is rules, a language model, an agent step, or a human decision.
- Evaluation cases added or updated before the code.
- Tests pass. Evaluation results attached if prompts, schemas, or rules changed.
- ADR written or updated if a decision was made.
- Data contract updated if a table changed.
- No new identified data in logs, fixtures, or the repository.

## 13. Working with a coding assistant

- Read `README.md`, the relevant ADRs, and the ticket before changing code.
- Plan first, then write the change. Show the plan and wait for approval for any change to an emergency rule, a schema, a prompt, or the audit path.
- Work on the synthetic layer. Never open or copy real identified data.
- If a requirement conflicts with a rule in section 6, stop and say so. Do not work around it.
- If a library or API is unfamiliar, check its current docs before writing code. Do not rely on memory for versions.
- Keep changes within the ticket's scope. Log out-of-scope ideas in `docs/assumptions.md`.
- Do not change the sample network's names or figures.

## 14. Never do

- Invent a diagnosis, medicine, dose, or prognosis, in code, data, or prompts.
- Approve a clinical rule, or set its status to approved.
- Show an unchecked model output to a patient, or write an AI-drafted note to a record before a doctor signs it.
- Remove or soften an emergency rule to make a test pass. Fix the rule or the extractor, and say which.
- Send identified data to an external service, or write it to a log.
- Hard-code prices, versions, thresholds, or message text in Python.
- Use the sensitive symptom `extra_marital_contacts` in any output, log, or prompt.
- Claim a metric you did not measure.

## 15. Current status

Update this section at each milestone.

- Triage prototype (in `sahyog-triage/`, to move into `triage/`): symptom catalogue (131 symptoms), 20 draft emergency rules and 37 phrases, all with status `DRAFT_PENDING_CLINICIAN`. Rule matcher with negation, fuzzy matching, and Hindi-English phrasing. Dialogue policy with 13 scripted cases and a question bank of 23 questions. Question wording and screening questions are not clinician-approved.
- Open clinical questions: whether chest pain alone is an emergency, breathing qualifiers, age bands for escalation, stroke and pre-eclampsia-like combinations, crisis wording and helpline numbers, and the phrase "fits".
- Known gaps: duration is recorded but not used in tier decisions. The screening questions do not yet cover self-harm or severe allergic reactions. Severity weights are not loaded until the dataset's severity file is joined.

## 16. Glossary

- **Red flag:** a sign that needs urgent human help now.
- **Checkpointer:** stores workflow state after each step, so a run can pause, resume, and be replayed.
- **Scope leak:** an answer that uses data the caller is not allowed to see. Held at zero.
- **Identified data:** health data that can be linked to a person. It stays in India and inside the hospital boundary.
- **ADR:** architecture decision record. One decision, its options, its consequences, and the trigger that would reverse it.
- **SOAP note:** a clinical note in four parts: subjective, objective, assessment, plan.
- **ABDM / ABHA:** India's digital health mission and the health ID it issues.
- **FHIR R4:** the HL7 standard for exchanging health records. Here, read-only.
- **p95:** the response time that 95% of requests beat.