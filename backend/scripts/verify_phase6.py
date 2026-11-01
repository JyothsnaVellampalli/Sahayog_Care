"""Validate Phase 6 migration reruns and booking invariants in a rolled-back transaction."""
import sys
import tempfile
from pathlib import Path
import apply_migration

root = Path(__file__).resolve().parents[1]
migration = (root / 'database/phase_6_followups_reports.sql').read_text(encoding='utf-8')
# Strip only the outer transaction; run the entire migration twice before assertions.
migration = migration.replace('\nbegin;\n', '\n', 1).removesuffix('commit;\n')
checks = """
do $test$
declare p uuid:=gen_random_uuid(); other_patient uuid:=gen_random_uuid(); d public.doctors%rowtype;
 old_slot uuid:=gen_random_uuid(); new_slot uuid:=gen_random_uuid(); prior uuid:=gen_random_uuid();
 key text:=gen_random_uuid()::text; result jsonb; again jsonb; failed boolean:=false;
begin
 select doctors.* into strict d from public.doctors join public.specialties s on s.id=doctors.specialty_id
 where s.code='ORTH' and doctors.is_active limit 1;
 insert into public.patients(id) values(p),(other_patient);
 insert into public.slots(id,doctor_id,starts_at,ends_at,status) values
  (old_slot,d.id,now()-interval '3 days',now()-interval '3 days'+interval '30 minutes','BOOKED'),
  (new_slot,d.id,now()+interval '100 days',now()+interval '100 days 30 minutes','OPEN');
 insert into public.appointments(id,slot_id,patient_id,status,idempotency_key,created_at,completed_at)
 values(prior,old_slot,p,'COMPLETED',gen_random_uuid()::text,now()-interval '4 days',now()-interval '3 days');
 begin
  perform public.book_appointment(other_patient,new_slot,'test',key,'[]','Normal',null,null,d.specialty_id,prior);
 exception when others then failed:=true; end;
 if not failed then raise exception 'Cross-patient link accepted'; end if;
 if (select status from public.slots where id=new_slot)<>'OPEN' then raise exception 'Failed follow-up consumed slot'; end if;
 result:=public.book_appointment(p,new_slot,'test',key,'[]','Normal',null,null,d.specialty_id,prior);
 again:=public.book_appointment(p,new_slot,'test',key,'[]','Normal',null,null,d.specialty_id,prior);
 if result->>'id' is distinct from again->>'id' or result->>'linked_appointment_id'<>prior::text then
  raise exception 'Link or retry failed'; end if;
 failed:=false;
 begin
  perform public.book_appointment(p,new_slot,'test',key,'[]','Normal',null,null,d.specialty_id,null);
 exception when others then failed:=true; end;
 if not failed then raise exception 'Retry changed link'; end if;
 failed:=false;
 begin
  update public.appointments set linked_appointment_id=null where id=(result->>'id')::uuid;
 exception when others then failed:=true; end;
 if not failed then raise exception 'Recorded link changed'; end if;
 insert into public.consultation_reports(id,appointment_id,report_type,title,findings,object_key)
 values(gen_random_uuid(),prior,'DOCUMENT','Test','{}','test-only');
end $test$;
"""
with tempfile.TemporaryDirectory(prefix='sahayog-phase6-') as directory:
    path = Path(directory) / 'verify.sql'
    path.write_text('begin;\n' + migration + migration + checks + '\nrollback;\n', encoding='utf-8')
    sys.argv = ['apply_migration.py', str(path)]
    result = apply_migration.main()
    if result == 0:
        print('Phase 6 migration rerun, ownership, atomic rollback, retry and report assertions passed; all changes rolled back.')
    raise SystemExit(result)
