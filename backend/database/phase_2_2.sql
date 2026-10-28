-- Phase 2.2: signed SOAP snapshots and atomic booking on the unified
-- appointment record.
--
-- Adds the finalised-record pointer (an immutable snapshot of SOAP + transcript
-- + signature stored in object storage), normalises severity onto the triage
-- categories (Emergency / Severe / Normal), tightens the active-slot index to
-- cover in-progress visits, and installs the atomic book_appointment() function
-- used by the booking flow. Idempotent: safe to re-run.
begin;
lock table public.appointments, public.slots in access exclusive mode;

-- Pointer to the signed, immutable finalisation snapshot in storage.
alter table public.appointments add column if not exists finalised_record_key text;

-- Normalise any legacy display severities to the triage categories.
update public.appointments
   set severity = case severity
                    when 'High'     then 'Emergency'
                    when 'Moderate' then 'Severe'
                    when 'Low'      then 'Normal'
                    else severity
                  end
 where severity in ('High', 'Moderate', 'Low');

-- Backfill severity from the human-readable reason where it is still unset.
update public.appointments
   set severity = case
                    when reason ilike '%Emergency%' then 'Emergency'
                    when reason ilike '%Severe%'    then 'Severe'
                    when reason ilike '%Normal%'    then 'Normal'
                  end
 where severity is null;

-- A slot is "taken" while a visit is BOOKED or IN_PROGRESS.
drop index if exists public.appointments_one_active_per_slot;
create unique index appointments_one_active_per_slot on public.appointments(slot_id)
  where status in ('BOOKED', 'IN_PROGRESS');
create index if not exists appointments_patient_idx on public.appointments(patient_id, created_at);

notify pgrst, 'reload schema';

-- Atomic booking: validates the slot, enforces idempotency, handles emergency
-- intakes, inserts the appointment and marks the slot BOOKED in one transaction.
create or replace function public.book_appointment(
  p_patient_id uuid, p_slot_id uuid, p_reason text, p_idempotency_key text,
  p_symptoms jsonb default '[]', p_severity text default null,
  p_history text default null, p_emergency_intake_id uuid default null
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
    p_history := intake.deidentified_text;
  elsif p_severity = 'Emergency' then
    raise exception 'Emergency appointments require manual intake assignment';
  end if;
  select * into chosen from public.slots where id = p_slot_id for update;
  if not found or chosen.status <> 'OPEN' or chosen.starts_at <= now() then
    raise exception 'Slot is no longer available';
  end if;
  insert into public.appointments(patient_id, slot_id, reason, idempotency_key,
                                 symptoms, severity, history, emergency_intake_id)
  values(p_patient_id, p_slot_id, p_reason, p_idempotency_key,
         p_symptoms, p_severity, p_history, p_emergency_intake_id)
  returning * into visit;
  update public.slots set status = 'BOOKED' where id = p_slot_id;
  if p_emergency_intake_id is not null then
    update public.emergency_intakes set is_met = true, met_at = now() where id = p_emergency_intake_id;
  end if;
  return to_jsonb(visit);
end $$;
revoke all on function public.book_appointment(uuid, uuid, text, text, jsonb, text, text, uuid) from public, anon, authenticated;
grant execute on function public.book_appointment(uuid, uuid, text, text, jsonb, text, text, uuid) to service_role;
commit;
