-- Durable consultation processing. Requires Phase 4.3.
begin;
alter table public.appointments add column if not exists soap_draft_key text;
create table if not exists public.consultation_jobs (
  id uuid primary key default gen_random_uuid(),
  appointment_id uuid not null references public.appointments(id),
  kind text not null check (kind in ('TRANSCRIPTION','SOAP')),
  dedupe_key text not null,
  state text not null default 'QUEUED' check (state in ('QUEUED','RUNNING','SUCCEEDED','FAILED')),
  payload jsonb not null default '{}',
  result_key text,
  source_hash text,
  error text,
  attempts integer not null default 0,
  lease_token uuid,
  lease_until timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(appointment_id,kind,dedupe_key)
);
create unique index if not exists consultation_one_active_soap on public.consultation_jobs(appointment_id)
  where kind='SOAP' and state in ('QUEUED','RUNNING');
create index if not exists consultation_jobs_queue on public.consultation_jobs(state,created_at);
alter table public.consultation_jobs enable row level security;
revoke all on public.consultation_jobs from anon,authenticated;
grant all on public.consultation_jobs to service_role;

create or replace function public.enqueue_consultation_job(p_visit uuid,p_kind text,p_dedupe text,p_payload jsonb)
returns jsonb language plpgsql set search_path=public as $$
declare v public.appointments%rowtype; j public.consultation_jobs%rowtype;
begin
  select * into v from public.appointments where id=p_visit for update;
  if not found or v.status<>'IN_PROGRESS' or v.consent_recorded is not true then
    raise exception 'Start this consultation with consent before processing.';
  end if;
  if p_kind='SOAP' then
    select * into j from public.consultation_jobs where appointment_id=p_visit and kind='SOAP' and state in ('QUEUED','RUNNING') limit 1;
    if found then return to_jsonb(j); end if;
  end if;
  insert into public.consultation_jobs(appointment_id,kind,dedupe_key,payload)
    values(p_visit,p_kind,p_dedupe,p_payload) on conflict(appointment_id,kind,dedupe_key) do nothing;
  select * into j from public.consultation_jobs where appointment_id=p_visit and kind=p_kind and dedupe_key=p_dedupe;
  return to_jsonb(j);
end $$;

drop function if exists public.claim_consultation_job();
create or replace function public.claim_consultation_job(p_visit uuid default null) returns jsonb language plpgsql set search_path=public as $$
declare j public.consultation_jobs%rowtype;
begin
  if not pg_try_advisory_xact_lock(hashtextextended('consultation-job-claim',0)) then return null; end if;
  update public.consultation_jobs set state='FAILED',error='Processing was interrupted repeatedly. Please retry.',updated_at=now()
    where state='RUNNING' and lease_until<now() and attempts>=3;
  select q.* into j from public.consultation_jobs q join public.appointments a on a.id=q.appointment_id
    where a.status='IN_PROGRESS' and (p_visit is null or q.appointment_id=p_visit)
      and (q.state='QUEUED' or (q.state='RUNNING' and q.lease_until<now()))
      and not exists(select 1 from public.consultation_jobs other where other.appointment_id=q.appointment_id
        and other.id<>q.id and other.state='RUNNING' and other.lease_until>=now())
    order by case q.kind when 'TRANSCRIPTION' then 0 else 1 end,q.created_at
    for update of q skip locked limit 1;
  if not found then return null; end if;
  update public.consultation_jobs set state='RUNNING',attempts=attempts+1,lease_token=gen_random_uuid(),
    lease_until=now()+interval '90 seconds',updated_at=now(),error=null where id=j.id returning * into j;
  return to_jsonb(j);
end $$;

create or replace function public.finish_consultation_job(p_job uuid,p_token uuid,p_key text,p_source text,p_expected_soap text)
returns boolean language plpgsql set search_path=public as $$
declare j public.consultation_jobs%rowtype; v public.appointments%rowtype;
begin
  select * into j from public.consultation_jobs where id=p_job;
  select * into v from public.appointments where id=j.appointment_id for update;
  select * into j from public.consultation_jobs where id=p_job for update;
  if j.state<>'RUNNING' or j.lease_token is distinct from p_token or j.lease_until<now() or v.status<>'IN_PROGRESS' then return false; end if;
  if j.kind='SOAP' and v.soap_draft_key is distinct from p_expected_soap then
    update public.consultation_jobs set state='FAILED',error='The summary changed during processing. Your saved edits were kept.',updated_at=now() where id=j.id;
    return false;
  end if;
  update public.consultation_jobs set state='SUCCEEDED',result_key=p_key,source_hash=p_source,lease_until=null,
    payload=payload-'audio_base64',updated_at=now() where id=j.id;
  if j.kind='SOAP' then
    update public.appointments set soap_draft_key=p_key where id=j.appointment_id;
  else
    -- The automatic next stage is enqueued in the same commit as transcript completion.
    insert into public.consultation_jobs(appointment_id,kind,dedupe_key,payload)
      values(j.appointment_id,'SOAP','after:'||j.id::text,'{}') on conflict do nothing;
  end if;
  return true;
end $$;

create or replace function public.retry_consultation_job(p_visit uuid,p_job uuid) returns jsonb language plpgsql set search_path=public as $$
declare j public.consultation_jobs%rowtype;
begin
  perform 1 from public.appointments where id=p_visit and status='IN_PROGRESS' for update;
  if not found then raise exception 'Consultation is not open.'; end if;
  select * into j from public.consultation_jobs where id=p_job and appointment_id=p_visit for update;
  if not found then raise exception 'Processing job not found.'; end if;
  if j.state='FAILED' then
    if j.kind='SOAP' and exists(select 1 from public.consultation_jobs where appointment_id=p_visit and kind='SOAP' and state in ('QUEUED','RUNNING')) then
      raise exception 'SOAP is already processing.';
    end if;
    update public.consultation_jobs set state='QUEUED',attempts=0,error=null,updated_at=now() where id=j.id returning * into j;
  end if;
  return to_jsonb(j);
end $$;

create or replace function public.save_consultation_draft(p_visit uuid,p_kind text,p_key text) returns void language plpgsql set search_path=public as $$
begin
  perform 1 from public.appointments where id=p_visit and status='IN_PROGRESS' for update;
  if not found then raise exception 'Consultation is not open.'; end if;
  if exists(select 1 from public.consultation_jobs where appointment_id=p_visit and state in ('QUEUED','RUNNING')) then
    raise exception 'Wait for processing to finish before editing the summary or transcript.';
  end if;
  if p_kind='SOAP' then update public.appointments set soap_draft_key=p_key where id=p_visit;
  elsif p_kind='TRANSCRIPTION' then update public.appointments set transcript_key=p_key where id=p_visit;
  else raise exception 'Unknown draft type.'; end if;
end $$;

create or replace function public.guard_consultation_processing() returns trigger language plpgsql set search_path=public as $$
begin
  if new.status='COMPLETED' and old.status is distinct from new.status and
    exists(select 1 from public.consultation_jobs where appointment_id=new.id and state in ('QUEUED','RUNNING')) then
    raise exception 'Audio or SOAP is still processing. Wait for completion before signing.';
  end if;
  return new;
end $$;
drop trigger if exists guard_consultation_processing on public.appointments;
create trigger guard_consultation_processing before update of status on public.appointments for each row execute function public.guard_consultation_processing();

revoke all on function public.enqueue_consultation_job(uuid,text,text,jsonb), public.claim_consultation_job(uuid),
 public.finish_consultation_job(uuid,uuid,text,text,text),public.retry_consultation_job(uuid,uuid),public.save_consultation_draft(uuid,text,text) from public,anon,authenticated;
grant execute on function public.enqueue_consultation_job(uuid,text,text,jsonb), public.claim_consultation_job(uuid),
 public.finish_consultation_job(uuid,uuid,text,text,text),public.retry_consultation_job(uuid,uuid),public.save_consultation_draft(uuid,text,text) to service_role;
notify pgrst,'reload schema';
commit;
