-- Phase 6.1: search ingestion job queue, decoupled from appointment lifecycle.
-- Requires phase_1_3.sql (appointments). Additive, rerunnable.
begin;

create table if not exists public.search_ingestion_jobs (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('APPOINTMENT','EMERGENCY_INTAKE','CONSULTATION_SIGNED','REPORT')),
  source_id uuid not null,
  state text not null default 'QUEUED' check (state in ('QUEUED','RUNNING','SUCCEEDED','FAILED')),
  payload jsonb not null default '{}',
  chunk_count integer,
  error text,
  attempts integer not null default 0,
  lease_token uuid,
  lease_until timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(kind,source_id)
);
create index if not exists search_ingestion_jobs_queue on public.search_ingestion_jobs(state,created_at);
alter table public.search_ingestion_jobs enable row level security;
revoke all on public.search_ingestion_jobs from anon,authenticated;
grant all on public.search_ingestion_jobs to service_role;

-- Unlike enqueue_consultation_job, this has no appointment-status/consent
-- guard: ingestion fires at booking time (BOOKED), emergency intake
-- creation, consultation signing (COMPLETED) and report upload, none of
-- which is "an open, consented consultation".
create or replace function public.enqueue_search_job(p_kind text,p_source_id uuid,p_payload jsonb)
returns jsonb language plpgsql set search_path=public as $$
declare j public.search_ingestion_jobs%rowtype;
begin
  insert into public.search_ingestion_jobs(kind,source_id,payload)
    values(p_kind,p_source_id,p_payload) on conflict(kind,source_id) do nothing;
  select * into j from public.search_ingestion_jobs where kind=p_kind and source_id=p_source_id;
  return to_jsonb(j);
end $$;

create or replace function public.claim_search_job() returns jsonb language plpgsql set search_path=public as $$
declare j public.search_ingestion_jobs%rowtype;
begin
  if not pg_try_advisory_xact_lock(hashtextextended('search-job-claim',0)) then return null; end if;
  update public.search_ingestion_jobs set state='FAILED',error='Processing was interrupted repeatedly. Please retry.',updated_at=now()
    where state='RUNNING' and lease_until<now() and attempts>=3;
  select * into j from public.search_ingestion_jobs
    where state='QUEUED' or (state='RUNNING' and lease_until<now())
    order by created_at for update skip locked limit 1;
  if not found then return null; end if;
  update public.search_ingestion_jobs set state='RUNNING',attempts=attempts+1,lease_token=gen_random_uuid(),
    lease_until=now()+interval '90 seconds',updated_at=now(),error=null where id=j.id returning * into j;
  return to_jsonb(j);
end $$;

create or replace function public.finish_search_job(p_job uuid,p_token uuid,p_chunk_count int)
returns boolean language plpgsql set search_path=public as $$
declare j public.search_ingestion_jobs%rowtype;
begin
  select * into j from public.search_ingestion_jobs where id=p_job for update;
  if not found or j.state<>'RUNNING' or j.lease_token is distinct from p_token or j.lease_until<now() then return false; end if;
  update public.search_ingestion_jobs set state='SUCCEEDED',chunk_count=p_chunk_count,lease_until=null,updated_at=now() where id=j.id;
  return true;
end $$;

create or replace function public.fail_search_job(p_job uuid,p_token uuid,p_error text)
returns boolean language plpgsql set search_path=public as $$
begin
  update public.search_ingestion_jobs set state='FAILED',error=p_error,lease_until=null,updated_at=now()
    where id=p_job and lease_token=p_token and state='RUNNING';
  return found;
end $$;

create or replace function public.retry_search_job(p_job uuid) returns jsonb language plpgsql set search_path=public as $$
declare j public.search_ingestion_jobs%rowtype;
begin
  select * into j from public.search_ingestion_jobs where id=p_job for update;
  if not found then raise exception 'Search ingestion job not found.'; end if;
  if j.state='FAILED' then
    if j.attempts>=3 then raise exception 'This job has failed too many times.'; end if;
    update public.search_ingestion_jobs set state='QUEUED',error=null,updated_at=now() where id=j.id returning * into j;
  end if;
  return to_jsonb(j);
end $$;

revoke all on function public.enqueue_search_job(text,uuid,jsonb),public.claim_search_job(),
 public.finish_search_job(uuid,uuid,int),public.fail_search_job(uuid,uuid,text),public.retry_search_job(uuid)
 from public,anon,authenticated;
grant execute on function public.enqueue_search_job(text,uuid,jsonb),public.claim_search_job(),
 public.finish_search_job(uuid,uuid,int),public.fail_search_job(uuid,uuid,text),public.retry_search_job(uuid)
 to service_role;
notify pgrst,'reload schema';
commit;
