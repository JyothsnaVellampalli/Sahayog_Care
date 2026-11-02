-- Isolated fixtures and every state change are rolled back.
begin;
set local lock_timeout='5s';
set local statement_timeout='30s';
do $$
declare
  test_visit uuid:=gen_random_uuid(); test_patient uuid:=gen_random_uuid(); test_slot uuid:=gen_random_uuid();
  test_doctor uuid; first_job jsonb; claimed jsonb; reclaimed jsonb; soap_job jsonb; other_job jsonb;
begin
  select id into test_doctor from public.doctors where is_active limit 1;
  insert into public.patients(id) values(test_patient);
  insert into public.slots(id,doctor_id,starts_at,ends_at,status)
    values(test_slot,test_doctor,clock_timestamp()+interval '110 years',clock_timestamp()+interval '110 years 1 hour','BOOKED');
  insert into public.appointments(id,patient_id,slot_id,status,idempotency_key,consent_recorded)
    values(test_visit,test_patient,test_slot,'IN_PROGRESS',test_visit::text,true);
  first_job:=public.enqueue_consultation_job(test_visit,'TRANSCRIPTION','recording-a','{"audio_key":"test-only"}')->'job';
  other_job:=public.enqueue_consultation_job(test_visit,'TRANSCRIPTION','recording-a','{"audio_key":"duplicate"}')->'job';
  assert first_job->>'id'=other_job->>'id','Upload retry duplicated the job';
  claimed:=public.claim_consultation_job(test_visit);
  assert claimed->>'state'='RUNNING','Worker did not claim queued audio';
  assert public.claim_consultation_job(test_visit) is null,'Concurrent worker claimed same visit';
  begin
    perform public.finalize_consultation_with_stock(test_visit,test_doctor,'test-snapshot','[]');
    assert false,'Signing succeeded while processing';
  exception when sqlstate 'P0001' then null; end;
  update public.consultation_jobs set lease_until=now()-interval '1 second' where id=(claimed->>'id')::uuid;
  reclaimed:=public.claim_consultation_job(test_visit);
  assert reclaimed->>'lease_token'<>claimed->>'lease_token','Recovery reused expired token';
  assert not public.finish_consultation_job((claimed->>'id')::uuid,(claimed->>'lease_token')::uuid,'stale-result',null,null), 'Expired worker published output';
  assert public.finish_consultation_job((reclaimed->>'id')::uuid,(reclaimed->>'lease_token')::uuid,'transcript-result',null,null), 'Recovered worker could not publish';
  assert exists(select 1 from public.consultation_jobs where appointment_id=test_visit and kind='SOAP' and state='QUEUED'),'Automatic SOAP was not enqueued';
  soap_job:=public.claim_consultation_job(test_visit);
  other_job:=public.enqueue_consultation_job(test_visit,'SOAP','manual','{}')->'job';
  assert other_job->>'id'=soap_job->>'id','Duplicate active SOAP request was accepted';
  -- Phase 5: a new recording while that SOAP job is RUNNING supersedes it.
  declare preempt jsonb;
  begin
    preempt:=public.enqueue_consultation_job(test_visit,'TRANSCRIPTION','recording-b','{"audio_key":"preempt"}');
    assert preempt->>'superseded_soap_job_id'=soap_job->>'id','Running SOAP job was not reported as superseded';
    assert (select state from public.consultation_jobs where id=(soap_job->>'id')::uuid)='FAILED','Superseded SOAP job was not failed';
    assert not public.finish_consultation_job((soap_job->>'id')::uuid,(soap_job->>'lease_token')::uuid,'late-result',null,null),
      'Superseded worker could still publish its SOAP result';
    assert (public.claim_consultation_job(test_visit))->>'kind'='TRANSCRIPTION','Preempting recording was not claimed next';
    update public.consultation_jobs set state='FAILED',error='test cleanup' where appointment_id=test_visit and kind='TRANSCRIPTION' and dedupe_key='recording-b';
  end;
  soap_job:=public.enqueue_consultation_job(test_visit,'SOAP','manual-retry','{}')->'job';
  -- A forced regenerate must supersede a still-QUEUED SOAP job, not dedupe to it.
  declare regen jsonb;
  begin
    regen:=public.enqueue_consultation_job(test_visit,'SOAP','regenerate-1','{"force":true}');
    assert regen->>'superseded_soap_job_id'=soap_job->>'id','Regenerate did not supersede the queued SOAP job';
    assert regen->'job'->>'id'<>soap_job->>'id','Regenerate reused the old job instead of creating a new one';
    assert (select state from public.consultation_jobs where id=(soap_job->>'id')::uuid)='FAILED','Superseded queued SOAP job was not failed';
  end;
  -- An automatic (non-forced) enqueue still dedupes to the active job.
  regen:=public.enqueue_consultation_job(test_visit,'SOAP','after:auto-chain','{}');
  assert regen->>'superseded_soap_job_id' is null,'Automatic enqueue should not supersede the active SOAP job';
  assert regen->'job'->>'id'=(select id::text from public.consultation_jobs where appointment_id=test_visit and kind='SOAP' and dedupe_key='regenerate-1'),
    'Automatic enqueue did not dedupe to the current active SOAP job';
  soap_job:=public.claim_consultation_job(test_visit);
  begin
    perform public.save_consultation_draft(test_visit,'SOAP','edit-during-job');
    assert false,'Manual SOAP changed during processing';
  exception when sqlstate 'P0001' then null; end;
  assert public.finish_consultation_job((soap_job->>'id')::uuid,(soap_job->>'lease_token')::uuid,'soap-result','source-hash',null),'SOAP result publication failed';
  assert (select soap_draft_key='soap-result' from public.appointments where id=test_visit),'SOAP pointer was not committed';
  perform public.save_consultation_draft(test_visit,'SOAP','reviewed-edit');
  assert (select soap_draft_key='reviewed-edit' from public.appointments where id=test_visit),'Manual edit did not persist';
  other_job:=public.enqueue_consultation_job(test_visit,'SOAP','retry-test','{}')->'job';
  update public.consultation_jobs set state='FAILED',error='test failure' where id=(other_job->>'id')::uuid;
  other_job:=public.retry_consultation_job(test_visit,(other_job->>'id')::uuid);
  assert other_job->>'state'='QUEUED','Failed job was not retryable';
  -- Retries are capped: attempts accumulate across retries (not reset to 0),
  -- so a job that keeps failing cannot be retried forever.
  update public.consultation_jobs set state='FAILED',attempts=3 where id=(other_job->>'id')::uuid;
  begin
    perform public.retry_consultation_job(test_visit,(other_job->>'id')::uuid);
    assert false,'A job retried 3+ times was retryable again';
  exception when sqlstate 'P0001' then null; end;
  -- Phase 5: TTL cleanup only removes terminal rows past the TTL window.
  declare purge_target uuid; before_count int; after_count int;
  begin
    insert into public.consultation_jobs(appointment_id,kind,dedupe_key,state,result_key)
      values(test_visit,'TRANSCRIPTION','stale-recording','SUCCEEDED','stale-result-key') returning id into purge_target;
    update public.consultation_jobs set updated_at=now()-interval '20 days' where id=purge_target;
    select count(*) into before_count from public.consultation_jobs where appointment_id=test_visit;
    perform public.purge_stale_consultation_jobs(15);
    select count(*) into after_count from public.consultation_jobs where appointment_id=test_visit;
    assert after_count=before_count-1,'TTL purge removed the wrong number of rows';
    assert not exists(select 1 from public.consultation_jobs where id=purge_target),'Stale row survived purge';
    assert exists(select 1 from public.consultation_jobs where appointment_id=test_visit and state='QUEUED'),'Active job was purged';
  end;
  -- Drafts can be saved while SOAP runs, including an explicit empty prescription.
  other_job:=public.write_consultation_prescription(test_visit,
    jsonb_build_object('items',jsonb_build_array(jsonb_build_object('brand_id',
      (select brand_id from public.pharmacy_brands limit 1),'dose','draft instructions'))),true,false);
  assert other_job->>'active'='true','Workspace was not saved';
  assert other_job->'items'->0->>'medicine_id' is not null,'Missing medicine foreign key';
  assert other_job->'items'->0->>'dose'='draft instructions','Draft instructions were lost';
  assert other_job->>'reviewed_at' is null,'Partial draft was marked reviewed';
  update public.consultation_jobs set state='FAILED' where appointment_id=test_visit and state='QUEUED';
  other_job:=public.write_consultation_prescription(test_visit,jsonb_build_object('items','[]'::jsonb,
    'doctor_id',test_doctor,'soap_draft_key','reviewed-edit','reviewed_at',now(),'soap_revision','test'),false,false);
  assert other_job->'items'='[]'::jsonb and other_job->>'active'='false','Empty review was not saved';
  -- A stale object-store import cannot overwrite a newer database prescription.
  perform public.write_consultation_prescription(test_visit,'{"items":[]}',true,true);
  assert public.read_consultation_prescription(test_visit)->>'active'='false','Import overwrote review';
  perform public.save_consultation_draft(test_visit,'SOAP','changed-after-review');
  begin
    perform public.finalize_consultation_with_stock(test_visit,test_doctor,'test-snapshot','[]');
    assert false,'Signing accepted a stale review';
  exception when sqlstate 'P0001' then null; end;
  perform public.write_consultation_prescription(test_visit,jsonb_build_object('items','[]'::jsonb,
    'doctor_id',test_doctor,'soap_draft_key','changed-after-review','reviewed_at',now()),false,false);
  perform public.finalize_consultation_with_stock(test_visit,test_doctor,'test-snapshot','[]');
  begin
    perform public.write_consultation_prescription(test_visit,'{"items":[]}',true,false);
    assert false,'Closed prescription was mutable';
  exception when sqlstate 'P0001' then null; end;
end $$;
rollback;
