-- Live database regression checks. Every fixture and stock change is rolled back.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '30s';

-- Build a reviewed relational prescription before exercising the stock transaction.
create function pg_temp.reviewed_finalize(v uuid,d uuid,k text,items jsonb)
returns jsonb language plpgsql as $$
declare rx jsonb;
begin
  if (select status from public.appointments where id=v)<>'COMPLETED' then
    select coalesce(jsonb_agg(e || '{"strength_form":"test","dose":"test","frequency":"test","duration":"test"}'::jsonb),'[]')
      into items from jsonb_array_elements(items) e;
    rx:=public.write_consultation_prescription(v,jsonb_build_object('items',items,'doctor_id',d,'reviewed_at',now()),false,false);
    items:=rx->'items';
  end if;
  return public.finalize_consultation_with_stock(v,d,k,items);
end $$;
do $$
declare
  doctor uuid;
  pharmacist uuid;
  patient uuid := gen_random_uuid();
  slot uuid := gen_random_uuid();
  visit uuid := gen_random_uuid();
  visit2 uuid := gen_random_uuid();
  slot2 uuid := gen_random_uuid();
  medicine text := 'TEST-' || gen_random_uuid()::text;
  test_brand text := 'TEST-A-' || gen_random_uuid()::text;
  test_brand2 text := 'TEST-Z-' || gen_random_uuid()::text;
  result jsonb;
  amount integer;
begin
  select id into doctor from public.doctors where is_active limit 1;
  select id into pharmacist from public.pharmacists where is_active limit 1;
  assert doctor is not null and pharmacist is not null, 'Seed a doctor and pharmacist before smoke checks';
  insert into public.patients(id) values (patient);
  insert into public.slots(id,doctor_id,starts_at,ends_at,status) values
    (slot,doctor,clock_timestamp() + interval '100 years',clock_timestamp() + interval '100 years 1 hour','BOOKED'),
    (slot2,doctor,clock_timestamp() + interval '101 years',clock_timestamp() + interval '101 years 1 hour','BOOKED');
  insert into public.appointments(id,patient_id,slot_id,status,idempotency_key,consent_recorded) values
    (visit,patient,slot,'IN_PROGRESS',visit::text,true),
    (visit2,patient,slot2,'IN_PROGRESS',visit2::text,true);
  insert into public.pharmacy_medicines(id,generic_name,specialty,composition,source_details)
    values(medicine,'Synthetic test medicine','cardiology','Synthetic test composition','{}');
  insert into public.pharmacy_brands(brand_id,medicine_id,brand,variant,source_status,stock_quantity) values
    (test_brand,medicine,'Synthetic A','Test only','unverified',10),
    (test_brand2,medicine,'Synthetic Z','Test only','unverified',0);
  -- A failure on the second item must roll back the first reservation too.
  begin
    perform pg_temp.reviewed_finalize(visit,doctor,'test-snapshot',
      jsonb_build_array(jsonb_build_object('brand_id',test_brand,'quantity',3),jsonb_build_object('brand_id',test_brand2,'quantity',1)));
    assert false, 'Insufficient stock was accepted';
  exception when sqlstate 'P0001' then null; end;
  select locked_quantity into amount from public.pharmacy_brands where brand_id=test_brand;
  assert amount=0, 'Partial reservation survived failed signing';
  assert not exists(select 1 from public.pharmacy_reservations where appointment_id=visit), 'Failed signing created reservation';
  assert (select status='IN_PROGRESS' from public.appointments where id=visit), 'Failed signing closed visit';

  result := pg_temp.reviewed_finalize(visit,doctor,'test-snapshot',
      jsonb_build_array(jsonb_build_object('brand_id',test_brand,'quantity',7)));
  assert result->>'status'='COMPLETED', 'Signing failed';
  assert (select medicine_id=medicine from public.pharmacy_reservations
    where appointment_id=visit and brand_id=test_brand), 'Reservation lost medicine identity';
  begin
    update public.pharmacy_reservations set medicine_id='incorrect-medicine' where appointment_id=visit;
    assert false, 'Reservation accepted a mismatched medicine';
  exception when foreign_key_violation then null; end;
  result := pg_temp.reviewed_finalize(visit,doctor,'retry-snapshot',
      jsonb_build_array(jsonb_build_object('brand_id',test_brand,'quantity',7)));
  assert result->>'finalised_record_key'='test-snapshot', 'Retry replaced snapshot';
  assert (select locked_quantity=7 and available_quantity=3 from public.pharmacy_brands where brand_id=test_brand), 'Retry double locked stock';
  begin
    perform pg_temp.reviewed_finalize(visit2,doctor,'test-2',jsonb_build_array(jsonb_build_object('brand_id',test_brand,'quantity',4)));
    assert false, 'Overbooking was accepted';
  exception when sqlstate 'P0001' then null; end;
  begin
    update public.pharmacy_brands set stock_quantity=6 where brand_id=test_brand;
    assert false, 'Physical count below reserved count was accepted';
  exception when check_violation then null; end;
  begin
    perform public.resolve_pharmacy_reservation(visit,pharmacist,'release');
    assert false, 'Early release was accepted';
  exception when sqlstate 'P0001' then null; end;
  update public.appointments set completed_at=now()-interval '24 hours' where id=visit;
  perform public.resolve_pharmacy_reservation(visit,pharmacist,'release');
  perform public.resolve_pharmacy_reservation(visit,pharmacist,'release');
  assert (select stock_quantity=10 and locked_quantity=0 from public.pharmacy_brands where brand_id=test_brand), 'Release changed physical count or double released';
  begin
    perform public.resolve_pharmacy_reservation(visit,pharmacist,'dispense');
    assert false, 'Released reservation was dispensed';
  exception when sqlstate 'P0001' then null; end;
  perform pg_temp.reviewed_finalize(visit2,doctor,'test-2',jsonb_build_array(jsonb_build_object('brand_id',test_brand,'quantity',4)));
  perform public.resolve_pharmacy_reservation(visit2,pharmacist,'dispense');
  perform public.resolve_pharmacy_reservation(visit2,pharmacist,'dispense');
  assert (select stock_quantity=6 and locked_quantity=0 and available_quantity=6 from public.pharmacy_brands where brand_id=test_brand), 'Collection did not deduct exactly once';
end $$;
rollback;
