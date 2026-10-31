# Phase 4 - Pharmacist Portal - Progress

## Phase 4.1 - Data ingestion and pharmacist portal

Status: Complete (2026-10-29).

### Delivered

- Validated and normalized the supplied catalogue into 90 medicines and 166
  brands across Cardiology, Orthopedics, Dermatology and Gastroenterology.
  Stable medicine/brand IDs, original variant descriptions, nullable manufacturers
  and source-verification status are preserved. Clinical source fields are
  retained as JSON without inferring new medical information.
- PostgreSQL tables: `pharmacy_medicines`, `pharmacy_brands`, `pharmacists`.
  Brands reference medicines; stock counts must be nonnegative integers.
- Random demo stock counts were requested by the project owner. The seed uses
  a fixed random seed for reproducibility, includes zero/low/available stock,
  and labels initial quantities as demo data. Re-ingestion updates catalogue
  metadata without overwriting stock quantities, their timestamps or demo flags.
- Pharmacists sign in by a pre-seeded phone number, matching doctor identification.
  Demo phone: `+919800000001`. The portal is accessible from the landing page at
  `/pharmacist/login`. Sign-out clears its tab-scoped browser session.
- Stock tab supports combined brand, specialty, composition and stock filters,
  pagination, refresh, clear filters, empty/error states and count updates.
  Low stock means 1–10 units; zero means out of stock. Saving a physical count
  clears the demo flag and records a timestamp.
- Signed consultations tab lists completed appointments with a saved signed
  record, newest first. Its detail view reads frozen SOAP and signature data,
  not a mutable draft. Transcripts and storage keys are omitted from the API.

### Scope and data interpretation

This is one shared pharmacy inventory. Counts are per supplied catalogue brand
entry, not per strength/pack/batch or hospital. Some variants contain several
strengths or combination products; the composition filter uses the parent
medicine's source composition. These records do not establish interchangeable
products. Exact SKUs, pack units, batch/expiry and price require additional source
data. The source's verification labels are retained, not independently verified.

Phone-only identification is a development workflow, with no password, OTP or
session-token authentication. API calls check that the pharmacist ID exists and
is active; that check is not secure authentication. New tables enable RLS and
deny direct anon/authenticated access; the backend uses the service role.

The Phase 4.1 stock updates replace the count (last saved value wins). Phase 4.3
below adds reservation constraints and collection/release status. The signed
queue includes all completed signed visits, with reservation status shown.

### Setup

From `backend`, after Phase 3:

```powershell
.venv/Scripts/python.exe scripts/build_pharmacy_seed.py
.venv/Scripts/python.exe scripts/apply_migration.py database/phase_4_1.sql
.venv/Scripts/python.exe scripts/apply_migration.py database/phase_4_1_seed.sql
.venv/Scripts/python.exe scripts/verify_pharmacy.py
```

The schema and seed are transactional and repeatable. No existing appointments,
consultations, patients, doctors or signatures are deleted. Restart the backend
and load the updated frontend after applying both SQL files.

### Verification

- Backend: 17 pharmacy tests passed, covering catalogue integrity, seed stock
  preservation, phone lookup, invalid counts, combined filters, pagination and
  completed/signed consultation boundaries.
- Frontend production build passed.
- Three Playwright tests passed: desktop/mobile flows, accessibility checks,
  count updates, session restoration/sign-out, signed detail and error retry.
- Browser tests use mocked APIs; database smoke checks are recorded separately.
- Both SQL migrations applied to the configured database. Read-only live checks
  confirmed 90 medicines, 166 brands, all four specialties, pharmacist lookup,
  combined filters, stock-state filters and the signed consultation joins.
  The live signed queue contained zero rows, so signed-detail storage was
  verified with fixtures rather than a real completed consultation.

## Phase 4.2 - Doctor prescriptions and SOAP layout

Status: Complete (2026-10-29).

- SOAP now follows design screen 4: a bordered two-column S/O/A/P layout on
  desktop, stacked on mobile, with summary actions in the header.
- Medicine review follows screens 8 and 9: catalogue-match cards, editable
  prescription rows, and a searchable side drawer with specialty, form and
  stock filters. The initial specialty comes from the doctor's database profile.
- Added `medicine_prescription` after SOAP validation in the consultation graph.
  It surfaces explicit brand/generic mentions in the assessment and plan only;
  it does not infer treatments or dosing. A negated or historical mention still
  needs doctor review. No allergy screening is claimed because no structured
  allergy source is currently available.
- Doctors add/remove medicines and specify the exact strength/form, dose,
  frequency, duration and optional instructions. Empty prescriptions can be
  explicitly reviewed and saved.
- Drafts and reviewed prescriptions now use Supabase prescription tables; graph
  suggestions are stored with SOAP results. Legacy prescription objects are imported.
  SOAP hashes invalidate prescription review after summary changes. Unknown or
  duplicate brands, missing instructions, stale saves, wrong-doctor requests
  and edits to closed visits are rejected.
- Signing freezes the database prescription alongside the SOAP/signature snapshot.
  Doctor, patient (including summary download), and pharmacist views combine both sources.
  Older signed visits without prescriptions remain readable.
- Verification: 55 backend tests, production build, and 14 Playwright tests passed
  across prescription, pharmacy and patient flows. Desktop/mobile screenshots
  and accessibility checks were included. Providers were stubbed in these tests.
- The processing follow-up requires the queue and prescription migrations after
  Phase 4.3. See [consultation processing](../Consultation-processing.md) for rollout.

## Phase 4.3 - Stock locking

Status: Complete (2026-10-29).

### Delivered

- Doctors enter a positive whole stock quantity for every prescribed brand.
  The quantity is supplied explicitly, never calculated from dose/frequency.
  Old unsigned prescription drafts without quantities require another review.
- `pharmacy_brands.locked_quantity` holds reserved units. Generated
  `available_quantity` is total physical stock minus locked units. These live on
  the brand table because that is the inventory unit established in Phase 4.1;
  generic medicine records do not have independent stock.
- `pharmacy_reservations` records each appointment/brand quantity and its
  LOCKED, RELEASED or DISPENSED status, resolution timestamp and pharmacist.
- `finalize_consultation_with_stock` locks the appointment and brand rows in a
  consistent order, checks every quantity, reserves stock and closes the visit in
  one transaction. Any shortage rolls everything back. Repeated signing returns
  the original completion without reserving twice or replacing its snapshot.
- The signed object is saved before the database transaction. A failed transaction
  may leave an unreferenced snapshot object; the visit stays open and the stored
  draft remains editable. No partial stock reservation survives.
- Stock filters and the doctor's catalogue use available quantity. The pharmacy
  stock screen shows available, reserved and total counts. Database constraints
  reject physical counts lower than reserved quantities.
- The signed queue and detail page show reservation status. A red overdue flag
  appears when a locked visit was signed at least 24 hours ago. Unlock requires
  pharmacist confirmation that the medicines were not collected. The server
  enforces the 24-hour threshold; the browser clock cannot bypass it.
- Mark collected consumes physical stock and releases the matching locked units.
  Unlock releases the locked units without changing physical stock. Both actions
  apply to the entire prescription atomically, are safe to retry, and reject
  conflicting actions after resolution. Signed clinical content remains unchanged.

### Rollout and verification

From `backend`:

```powershell
.venv/Scripts/python.exe scripts/apply_migration.py database/phase_4_3.sql
.venv/Scripts/python.exe scripts/verify_pharmacy.py
.venv/Scripts/python.exe scripts/verify_stock_transactions.py
```

The migration was applied to the configured database. It is additive and does
not retrospectively reserve stock for older signed visits. Deploy the new backend
and frontend together after migration; the old signing endpoint does not reserve
stock. Restart the API and reload browser tabs.

- 79 targeted backend tests passed (prescriptions, signing, SOAP, pharmacy,
  stock reservations and patient details).
- Eight prescription/pharmacy browser tests passed, including desktop/mobile
  review, 24-hour controls, confirmation cancellation, collection and unlock.
  The earlier Phase 4.2 run also passed all 14 patient/pharmacy/prescription tests.
- Production frontend build passed; desktop and mobile screenshots were inspected.
- Live read-only checks passed for catalogue counts, available/reserved stock,
  doctor's specialty defaults and consultation joins.
- Live transactional SQL checks passed for all-or-nothing reservations, shortages,
  signing retries, oversubscription rejection, protected stock edits, early-release
  rejection, the exact 24-hour boundary, release retries and collection retries.
  Synthetic fixtures and every test stock mutation were rolled back. These are
  functional transaction checks, not a concurrent load test.

The inventory still represents catalogue brand entries rather than separate
strength/pack/batch SKUs. Partial collection, partial unlocking, reservation
extensions and automatic release are outside this phase. Reservations remain
locked until a pharmacist explicitly records collection or unlocks them.
