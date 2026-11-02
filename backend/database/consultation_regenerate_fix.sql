-- Regenerate SOAP must actually regenerate. Requires phase_5_consultation_memory.sql.
-- Additive, rerunnable.
begin;

-- enqueue_consultation_job's SOAP branch used to hand back any already
-- QUEUED/RUNNING SOAP job unconditionally -- including a stuck or still
-- -processing one from an earlier attempt. Clicking "Regenerate SOAP" (which
-- always sends {"force": true}) could therefore silently attach to that old
-- job instead of starting a fresh translate+SOAP run. An automatic
-- SOAP-after-transcription enqueue (force absent) still dedupes to the
-- existing active job as before -- only an explicit forced regenerate now
-- supersedes it.
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
    if found then
      if p_payload->>'force'='true' then
        update public.consultation_jobs set state='FAILED',error='Superseded by a new regenerate request.',lease_until=null,updated_at=now()
          where id=j.id returning id into superseded;
      else
        return jsonb_build_object('job',to_jsonb(j),'superseded_soap_job_id',null);
      end if;
    end if;
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

notify pgrst,'reload schema';
commit;
