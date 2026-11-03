-- Isolated fixtures and every state change are rolled back.
begin;
set local lock_timeout='5s';
set local statement_timeout='30s';
do $$
declare
  test_visit uuid:=gen_random_uuid();
  first_job jsonb; claimed jsonb; reclaimed jsonb; other_job jsonb;
begin
  first_job:=public.enqueue_search_job('APPOINTMENT',test_visit,'{}');
  other_job:=public.enqueue_search_job('APPOINTMENT',test_visit,'{}');
  assert first_job->>'id'=other_job->>'id','Duplicate enqueue created a second job';
  claimed:=public.claim_search_job();
  assert claimed->>'state'='RUNNING','Worker did not claim the queued job';
  assert claimed->>'id'=first_job->>'id','Claimed the wrong job';
  update public.search_ingestion_jobs set lease_until=now()-interval '1 second' where id=(claimed->>'id')::uuid;
  reclaimed:=public.claim_search_job();
  assert reclaimed->>'lease_token'<>claimed->>'lease_token','Recovery reused the expired lease token';
  assert not public.finish_search_job((claimed->>'id')::uuid,(claimed->>'lease_token')::uuid,1),
    'Expired worker could still publish its result';
  assert public.finish_search_job((reclaimed->>'id')::uuid,(reclaimed->>'lease_token')::uuid,3),
    'Recovered worker could not publish its result';
  assert (select state='SUCCEEDED' and chunk_count=3 from public.search_ingestion_jobs where id=(reclaimed->>'id')::uuid),
    'Chunk count was not committed on success';

  -- A different kind for the same source_id is a distinct job.
  other_job:=public.enqueue_search_job('CONSULTATION_SIGNED',test_visit,'{}');
  assert other_job->>'id'<>first_job->>'id','Different kinds were deduped together';

  -- Retry is capped at 3 attempts.
  update public.search_ingestion_jobs set state='FAILED',attempts=3 where id=(other_job->>'id')::uuid;
  begin
    perform public.retry_search_job((other_job->>'id')::uuid);
    assert false,'A job retried 3+ times was retryable again';
  exception when sqlstate 'P0001' then null; end;
end $$;
rollback;
