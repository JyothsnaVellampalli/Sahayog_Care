-- Phase 1.4 migration: patient login + profile fields, and appointment reason.
--
-- Login is phone + password (dev stage, no OTP). Supabase Auth backs it via
-- email + password; the phone is the business identifier and auth_user_id links
-- the profile to the Supabase Auth user. `role` is kept for future role-based
-- authorization.
--
-- Idempotent: all columns use "if not exists". Safe to run more than once.

-- patients: add login + registration fields.
alter table public.patients add column if not exists phone        text;
alter table public.patients add column if not exists full_name    text;
alter table public.patients add column if not exists email        text;
alter table public.patients add column if not exists age          smallint;
alter table public.patients add column if not exists auth_user_id uuid;
alter table public.patients add column if not exists role         text not null default 'patient';

-- Constraints (added separately so re-runs don't fail on duplicates).
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'patients_phone_key'
  ) then
    alter table public.patients add constraint patients_phone_key unique (phone);
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'patients_age_range'
  ) then
    alter table public.patients
      add constraint patients_age_range check (age is null or (age >= 0 and age <= 120));
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'patients_role_check'
  ) then
    alter table public.patients
      add constraint patients_role_check
      check (role in ('patient', 'doctor', 'front_desk', 'admin'));
  end if;
end $$;

create index if not exists patients_phone_idx on public.patients (phone);
create index if not exists patients_auth_user_idx on public.patients (auth_user_id);

-- appointments: a human-readable reason shown in "My appointments"
-- (e.g. "Cardiology — Severe"). Disease is not computed; this is the summary.
alter table public.appointments add column if not exists reason text;
