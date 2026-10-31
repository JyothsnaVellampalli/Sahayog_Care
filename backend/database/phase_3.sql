-- Phase 3 schema switch. Requires Phase 2.2. Stop API/workers and back up first.
-- Run phase_3_cleanup.sql before the first switch: symptom IDs have new meanings.
-- Re-runnable after migration; does not delete new Phase 3 appointments.
begin;
lock table public.appointments, public.slots in access exclusive mode;
do $$
begin
  if exists (select 1 from information_schema.columns where table_schema = 'public'
             and table_name = 'appointments' and column_name = 'history') then
    if exists (select 1 from public.appointments) or exists (select 1 from public.emergency_intakes) then
      raise exception 'Run phase_3_cleanup.sql before switching symptom catalogues';
    end if;
    alter table public.appointments rename column history to symptom_text;
  end if;
end $$;
alter table public.appointments
  add column if not exists symptom_text text,
  add column if not exists specialty_id uuid references public.specialties(id),
  drop column if exists legacy_consultation_id,
  drop column if exists allergies,
  drop column if exists vitals;
create index if not exists appointments_specialty_idx on public.appointments(specialty_id);
insert into public.specialties(code, name, description) values
 ('CARD','Cardiology','Heart and blood vessel conditions'),
 ('ORTH','Orthopedics','Bones, joints, muscles and ligaments'),
 ('DERM','Dermatology','Skin, hair and nail conditions'),
 ('GAST','Gastroenterology','Stomach, intestine, liver and pancreas')
on conflict(code) do update set name = excluded.name, description = excluded.description;
-- Keep other specialties and their doctors intact; the API filters MVP choices.
-- Drop old RPC signature to avoid ambiguous PostgREST overload resolution.
drop function if exists public.book_appointment(uuid,uuid,text,text,jsonb,text,text,uuid);
create or replace function public.book_appointment(
  p_patient_id uuid, p_slot_id uuid, p_reason text, p_idempotency_key text,
  p_symptoms jsonb default '[]', p_severity text default null,
  p_symptom_text text default null, p_emergency_intake_id uuid default null, p_specialty_id uuid default null
) returns jsonb language plpgsql set search_path = public as $$
declare
  visit public.appointments%rowtype;
  chosen public.slots%rowtype;
  intake public.emergency_intakes%rowtype;
begin
  if p_patient_id is null or nullif(p_idempotency_key, '') is null then
    raise exception 'Patient and idempotency key are required';
  end if;
  -- Serialize retries even if they arrive before the first INSERT commits.
  perform pg_advisory_xact_lock(hashtextextended(p_idempotency_key, 0));
  select * into visit from public.appointments where idempotency_key = p_idempotency_key;
  if found then
    if visit.patient_id <> p_patient_id or visit.slot_id <> p_slot_id
       or visit.emergency_intake_id is distinct from p_emergency_intake_id then
      raise exception 'Idempotency key already used for a different booking';
    end if;
    return to_jsonb(visit);
  end if;
  if p_emergency_intake_id is not null then
    select * into intake from public.emergency_intakes where id = p_emergency_intake_id for update;
    if not found or intake.is_met or intake.patient_id is distinct from p_patient_id then
      raise exception 'Emergency intake is unavailable or belongs to another patient';
    end if;
    p_symptoms := intake.symptoms;
    p_severity := 'Emergency';
    p_symptom_text := intake.deidentified_text;
    p_specialty_id := (intake.specialty->>'id')::uuid;
  elsif p_severity = 'Emergency' then
    raise exception 'Emergency appointments require manual intake assignment';
  end if;
  select * into chosen from public.slots where id = p_slot_id for update;
  if not found or chosen.status <> 'OPEN' or chosen.starts_at <= now() then
    raise exception 'Slot is no longer available';
  end if;
  if p_specialty_id is not null then
    if not exists (select 1 from public.specialties where id = p_specialty_id
                   and code in ('CARD', 'ORTH', 'DERM', 'GAST')) then
      raise exception 'Unsupported specialty';
    end if;
    if p_emergency_intake_id is null and not exists (
      select 1 from public.doctors where id = chosen.doctor_id and specialty_id = p_specialty_id
    ) then
      raise exception 'Doctor does not match the assessed specialty';
    end if;
  end if;
  if p_emergency_intake_id is null and not exists (
    select 1 from public.doctors d join public.specialties s on s.id = d.specialty_id
    where d.id = chosen.doctor_id and d.is_active and s.code in ('CARD','ORTH','DERM','GAST')
  ) then
    raise exception 'Doctor is not available for MVP booking';
  end if;
  insert into public.appointments(patient_id, slot_id, reason, idempotency_key,
                                 symptoms, severity, symptom_text, emergency_intake_id, specialty_id)
  values(p_patient_id, p_slot_id, p_reason, p_idempotency_key,
         p_symptoms, p_severity, p_symptom_text, p_emergency_intake_id, p_specialty_id)
  returning * into visit;
  update public.slots set status = 'BOOKED' where id = p_slot_id;
  if p_emergency_intake_id is not null then
    update public.emergency_intakes set is_met = true, met_at = now() where id = p_emergency_intake_id;
  end if;
  return to_jsonb(visit);
end $$;
revoke all on function public.book_appointment(uuid, uuid, text, text, jsonb, text, text, uuid, uuid) from public, anon, authenticated;
grant execute on function public.book_appointment(uuid, uuid, text, text, jsonb, text, text, uuid, uuid) to service_role;
notify pgrst, 'reload schema';
commit;
