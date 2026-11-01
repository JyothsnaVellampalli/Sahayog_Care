-- Phase 6: one appointments record, follow-up links, helpdesk and reports.
-- Requires phase_3.sql and consultation_prescriptions.sql. Additive, rerunnable.
begin;
alter table public.appointments add column if not exists linked_appointment_id uuid references public.appointments(id);
alter table public.emergency_intakes add column if not exists linked_appointment_id uuid references public.appointments(id);
create index if not exists appointments_linked_idx on public.appointments(linked_appointment_id);

create or replace function public.guard_followup_link() returns trigger language plpgsql set search_path=public as $$
declare prior public.appointments%rowtype;
begin
 if TG_OP='UPDATE' and old.linked_appointment_id is not null and
    new.linked_appointment_id is distinct from old.linked_appointment_id then
   raise exception 'A recorded follow-up link cannot be changed.';
 end if;
 if new.linked_appointment_id is null then return new; end if;
 select * into prior from public.appointments where id=new.linked_appointment_id for share;
 if not found or prior.patient_id is distinct from new.patient_id or prior.status<>'COMPLETED' then
   raise exception 'Choose a completed appointment belonging to this patient.';
 end if;
 if TG_TABLE_NAME='appointments' then
   if new.id=prior.id or prior.completed_at is null or prior.completed_at>new.created_at then
     raise exception 'The related appointment must precede this appointment.';
   end if;
   if exists (with recursive chain as (
     select id,linked_appointment_id from public.appointments where id=new.linked_appointment_id
     union
     select a.id,a.linked_appointment_id from public.appointments a join chain c on a.id=c.linked_appointment_id
   ) select 1 from chain where id=new.id) then
     raise exception 'Follow-up links cannot form a cycle.';
   end if;
 end if;
 return new;
end $$;
drop trigger if exists guard_followup_link on public.appointments;
create trigger guard_followup_link before insert or update of linked_appointment_id,patient_id on public.appointments
 for each row execute function public.guard_followup_link();
drop trigger if exists guard_followup_link on public.emergency_intakes;
create trigger guard_followup_link before insert or update of linked_appointment_id,patient_id on public.emergency_intakes
 for each row execute function public.guard_followup_link();

-- Preserve all existing booking checks and stock behavior; wrap the atomic RPC.
do $$ begin
 if to_regprocedure('public.book_appointment_base(uuid,uuid,text,text,jsonb,text,text,uuid,uuid)') is null then
   alter function public.book_appointment(uuid,uuid,text,text,jsonb,text,text,uuid,uuid) rename to book_appointment_base;
 end if;
end $$;
create or replace function public.book_appointment(
 p_patient_id uuid,p_slot_id uuid,p_reason text,p_idempotency_key text,
 p_symptoms jsonb default '[]',p_severity text default null,p_symptom_text text default null,
 p_emergency_intake_id uuid default null,p_specialty_id uuid default null,p_linked_appointment_id uuid default null
) returns jsonb language plpgsql set search_path=public as $$
declare result jsonb; existing public.appointments%rowtype; linked uuid:=p_linked_appointment_id;
begin
 perform pg_advisory_xact_lock(hashtextextended(p_idempotency_key,0));
 if p_emergency_intake_id is not null then
   select linked_appointment_id into linked from public.emergency_intakes where id=p_emergency_intake_id;
 end if;
 select * into existing from public.appointments where idempotency_key=p_idempotency_key;
 if found and existing.linked_appointment_id is distinct from linked then
   raise exception 'Idempotency key already used with a different related appointment.';
 end if;
 result:=public.book_appointment_base(p_patient_id,p_slot_id,p_reason,p_idempotency_key,p_symptoms,p_severity,
                                     p_symptom_text,p_emergency_intake_id,p_specialty_id);
 if linked is not null then
   update public.appointments set linked_appointment_id=linked where id=(result->>'id')::uuid returning to_jsonb(appointments.*) into result;
 end if;
 return result;
end $$;
revoke all on function public.book_appointment(uuid,uuid,text,text,jsonb,text,text,uuid,uuid,uuid) from public,anon,authenticated;
grant execute on function public.book_appointment(uuid,uuid,text,text,jsonb,text,text,uuid,uuid,uuid) to service_role;

create table if not exists public.helpdesk_staff (
 id uuid primary key default gen_random_uuid(),full_name text not null,phone text not null unique,is_active boolean not null default true);
alter table public.helpdesk_staff enable row level security;
revoke all on public.helpdesk_staff from anon,authenticated;
grant all on public.helpdesk_staff to service_role;
insert into public.helpdesk_staff(full_name,phone) values('Demo Helpdesk','+919800000002') on conflict(phone) do nothing;

-- Compatible with the optional historical demo report table.
create table if not exists public.consultation_reports (
 id uuid primary key default gen_random_uuid(),appointment_id uuid not null references public.appointments(id),
 report_type text not null,title text not null,findings jsonb not null default '{}',object_key text not null,
 reported_at timestamptz not null default now(),is_synthetic boolean not null default false);
alter table public.consultation_reports
 add column if not exists content_type text,
 add column if not exists size_bytes integer,
 add column if not exists uploaded_by uuid,
 add column if not exists uploaded_role text;
alter table public.consultation_reports alter column reported_at set default now();
create index if not exists consultation_reports_appointment_idx on public.consultation_reports(appointment_id);
alter table public.consultation_reports enable row level security;
revoke all on public.consultation_reports from anon,authenticated;
grant all on public.consultation_reports to service_role;
notify pgrst,'reload schema';
commit;
