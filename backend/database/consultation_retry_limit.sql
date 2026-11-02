-- Cap manual retries of a failed consultation job. Requires consultation_processing.sql.
-- Additive, rerunnable.
begin;

-- retry_consultation_job used to reset attempts to 0 on every manual retry,
-- so a repeatedly-failing job (e.g. a slow/unreliable configured model) could
-- be retried forever, each retry re-running the full translate+SOAP LLM
-- pipeline. Attempts now accumulate across both automatic lease-expiry
-- recovery (claim_consultation_job) and manual retries, and are capped.
create or replace function public.retry_consultation_job(p_visit uuid,p_job uuid) returns jsonb language plpgsql set search_path=public as $$
declare j public.consultation_jobs%rowtype;
begin
  perform 1 from public.appointments where id=p_visit and status='IN_PROGRESS' for update;
  if not found then raise exception 'Consultation is not open.'; end if;
  select * into j from public.consultation_jobs where id=p_job and appointment_id=p_visit for update;
  if not found then raise exception 'Processing job not found.'; end if;
  if j.state='FAILED' then
    if j.attempts>=3 then
      raise exception 'This job has failed too many times. Start a new recording or regenerate SOAP to try again.';
    end if;
    if j.kind='SOAP' and exists(select 1 from public.consultation_jobs where appointment_id=p_visit and kind='SOAP' and state in ('QUEUED','RUNNING')) then
      raise exception 'SOAP is already processing.';
    end if;
    update public.consultation_jobs set state='QUEUED',error=null,updated_at=now() where id=j.id returning * into j;
  end if;
  return to_jsonb(j);
end $$;

revoke all on function public.retry_consultation_job(uuid,uuid) from public,anon,authenticated;
grant execute on function public.retry_consultation_job(uuid,uuid) to service_role;
notify pgrst,'reload schema';
commit;
