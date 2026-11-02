-- Phase 5: consultation memory. Requires consultation_processing.sql. Additive, rerunnable.
begin;

-- Permanent audio pointer, independent of consultation_jobs row retention
-- (Workstream A: recordings are kept in storage indefinitely, as proof).
alter table public.consultation_recordings add column if not exists audio_key text;

create or replace function public.save_consultation_recording_audio(p_visit uuid,p_recording uuid,p_key text)
returns void language plpgsql set search_path=public as $$
begin
  insert into public.consultation_recordings(appointment_id,recording_id,provider_state,audio_key)
    values(p_visit,p_recording,'{}'::jsonb,p_key)
  on conflict(appointment_id,recording_id) do update set audio_key=excluded.audio_key,updated_at=now();
end $$;

-- Preemption (Workstream B): queuing a new TRANSCRIPTION job for a visit
-- that has a RUNNING SOAP job supersedes it immediately, rather than letting
-- it finish. finish_consultation_job's existing RUNNING+lease_token guard
-- already discards that worker's eventual (wasted) publish for free.
create or replace function public.enqueue_consultation_job(p_visit uuid,p_kind text,p_dedupe text,p_payload jsonb)
returns jsonb language plpgsql set search_path=public as $$
declare v public.appointments%rowtype; j public.consultation_jobs%rowtype; superseded uuid;
begin
  select * into v from public.appointments where id=p_visit for update;
  if not found or v.status<>'IN_PROGRESS' or v.consent_recorded is not true then
    raise exception 'Start this consultation with consent before processing.';
  end if;
  if p_kind='SOAP' then
    select * into j from public.consultation_jobs where appointment_id=p_visit and kind='SOAP' and state in ('QUEUED','RUNNING') limit 1;
    if found then return jsonb_build_object('job',to_jsonb(j),'superseded_soap_job_id',null); end if;
  elsif p_kind='TRANSCRIPTION' then
    update public.consultation_jobs set state='FAILED',error='Superseded by a new recording.',lease_until=null,updated_at=now()
      where appointment_id=p_visit and kind='SOAP' and state='RUNNING'
      returning id into superseded;
  end if;
  insert into public.consultation_jobs(appointment_id,kind,dedupe_key,payload)
    values(p_visit,p_kind,p_dedupe,p_payload) on conflict(appointment_id,kind,dedupe_key) do nothing;
  select * into j from public.consultation_jobs where appointment_id=p_visit and kind=p_kind and dedupe_key=p_dedupe;
  return jsonb_build_object('job',to_jsonb(j),'superseded_soap_job_id',superseded);
end $$;

-- TTL cleanup (Workstream D): purge terminal job rows older than the TTL and
-- return the storage keys they referenced so the caller can delete them.
-- Never touches QUEUED/RUNNING rows, signed records, signatures or recordings.
create or replace function public.purge_stale_consultation_jobs(p_ttl_days int default 15)
returns table(result_key text,audio_key text) language plpgsql set search_path=public as $$
begin
  return query
  delete from public.consultation_jobs
    where state in ('SUCCEEDED','FAILED') and updated_at<now()-(p_ttl_days||' days')::interval
  returning consultation_jobs.result_key, consultation_jobs.payload->>'audio_key';
end $$;

revoke all on function public.save_consultation_recording_audio(uuid,uuid,text),
 public.purge_stale_consultation_jobs(int) from public,anon,authenticated;
grant execute on function public.save_consultation_recording_audio(uuid,uuid,text),
 public.purge_stale_consultation_jobs(int) to service_role;
notify pgrst,'reload schema';
commit;
