-- Destructive reset of ALL booking/visit data. Stop the backend before running.
-- Preserves patients, doctors, signatures, hospitals, specialties, availability,
-- and slot rows/times. Every slot (including past slots) becomes OPEN.
-- Works before or after the unified-appointments migration.
-- Does not delete transcript, SOAP, or transcription-job files in S3/local storage.

-- Clear a transaction left aborted by the failed migration, if any.
rollback;
begin;

lock table public.slots, public.appointments, public.emergency_intakes
  in access exclusive mode;

-- Delete dependent visits first. No CASCADE: unexpected dependencies should
-- abort this reset rather than delete unrelated tables automatically.
do $$
begin
  if to_regclass('public.consultations') is not null then
    execute 'delete from public.consultations';
  end if;
  if to_regclass('public.consultations_legacy_archive') is not null then
    execute 'delete from public.consultations_legacy_archive';
  end if;
end $$;

delete from public.appointments;
delete from public.emergency_intakes;
update public.slots set status = 'OPEN' where status is distinct from 'OPEN';

commit;

-- Expected: appointments = 0, emergency_intakes = 0, slots_not_open = 0.
select
  (select count(*) from public.appointments) as appointments,
  (select count(*) from public.emergency_intakes) as emergency_intakes,
  (select count(*) from public.slots) as slots_kept,
  (select count(*) from public.slots where status is distinct from 'OPEN') as slots_not_open;
