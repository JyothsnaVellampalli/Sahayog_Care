-- Phase 2.1: doctor portal (Consultation Scribe).
--
-- Adds doctor identity + signature fields, gives every seeded (synthetic)
-- doctor a unique dummy phone (doctors are identified by phone alone at this
-- dev stage - no password/OTP), and adds the consultation fields directly onto
-- `appointments` (the unified visit record; there is no separate consultations
-- table). Idempotent: safe to re-run.
begin;

-- doctors: identity + signature fields.
alter table public.doctors add column if not exists phone          text;
alter table public.doctors add column if not exists email          text;
alter table public.doctors add column if not exists auth_user_id   uuid;
-- Storage reference for the uploaded signature (S3 key or local path).
alter table public.doctors add column if not exists signature_key  text;
alter table public.doctors add column if not exists signature_uploaded_at timestamptz;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'doctors_phone_key') then
    alter table public.doctors add constraint doctors_phone_key unique (phone);
  end if;
end $$;

create index if not exists doctors_phone_idx on public.doctors (phone);
create index if not exists doctors_auth_user_idx on public.doctors (auth_user_id);

-- Give every synthetic doctor a unique dummy phone so they can sign in by phone.
-- Non-destructive: only fills doctors whose phone is NULL, assigns a
-- deterministic number by doctor_code order, and skips values already taken so
-- the unique constraint (doctors_phone_key) always holds.
-- Numbering scheme: +9190000000NN (NN = zero-padded sequence).
do $$
declare
  rec       record;
  seq       int := 1;
  candidate text;
begin
  for rec in
    select id
      from public.doctors
     where phone is null and is_synthetic
     order by doctor_code
  loop
    loop
      candidate := '+9190000000' || lpad(seq::text, greatest(2, length(seq::text)), '0');
      exit when not exists (
        select 1 from public.doctors where phone = candidate
      );
      seq := seq + 1;
    end loop;

    update public.doctors set phone = candidate where id = rec.id;
    seq := seq + 1;
  end loop;
end $$;

-- appointments: consultation fields (the unified visit record).
alter table public.appointments
  add column if not exists severity text,
  add column if not exists symptoms jsonb not null default '[]'::jsonb,
  add column if not exists history text,
  add column if not exists allergies text,
  add column if not exists vitals text,
  add column if not exists consent_recorded boolean not null default false,
  add column if not exists transcript_key text,
  add column if not exists started_at timestamptz,
  add column if not exists completed_at timestamptz,
  add column if not exists legacy_consultation_id uuid unique,
  add column if not exists emergency_intake_id uuid unique references public.emergency_intakes(id);

-- A consultation can be in progress; widen the status check accordingly.
alter table public.appointments drop constraint if exists appointments_status_check;
alter table public.appointments add constraint appointments_status_check
  check (status in ('BOOKED', 'IN_PROGRESS', 'CANCELLED', 'COMPLETED', 'NO_SHOW'));

notify pgrst, 'reload schema';
commit;
