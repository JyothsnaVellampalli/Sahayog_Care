-- Phase 1.4 follow-up: emergency intakes.
--
-- Every time a patient's condition is classified as Emergency, we record it
-- here (the booking flow ends without a slot, so there is no appointments row).
-- Front desk / staff pick these up; when a case is attended to, `is_met` is set
-- true and a normal appointments row is created, so it is not shown twice.
--
-- Idempotent.

create table if not exists public.emergency_intakes (
  id                 uuid primary key default gen_random_uuid(),
  patient_id         uuid references public.patients(id),
  -- Readable list of selected symptoms (labels), stored as JSON for the UI/staff.
  symptoms           jsonb not null default '[]'::jsonb,
  -- De-identified free text (identifiers already removed before storage).
  deidentified_text  text,
  category           text not null default 'Emergency',
  -- Per-category weightage from the classifier, for audit.
  scores             jsonb not null default '{}'::jsonb,
  -- Flipped to true by staff once the case is attended to.
  is_met             boolean not null default false,
  met_at             timestamptz,
  created_at         timestamptz not null default now()
);

create index if not exists emergency_intakes_patient_idx
  on public.emergency_intakes (patient_id);

-- The common query: a patient's open (not yet attended) emergencies.
create index if not exists emergency_intakes_open_idx
  on public.emergency_intakes (patient_id) where is_met = false;
