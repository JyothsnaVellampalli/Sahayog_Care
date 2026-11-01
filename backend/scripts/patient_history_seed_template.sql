-- GENERATED: scripts/build_patient_history_seed.py; source: cases.json.
-- v2: 5 existing demo logins; visit counts 5,3,2,2,1; 8 follow-up links.
-- Requires Phase 6. Replaces ONLY known v1 demo history; retains Auth and patient IDs.
-- No stock, reservations, dispensing, real signatures or AI calls.
-- Setup helper uploads objects BEFORE running this SQL. See README.md.
BEGIN;
SELECT pg_advisory_xact_lock(hashtextextended('demo-patient-history',0));
LOCK TABLE public.appointments, public.slots, public.patients, public.consultation_reports,
 public.consultation_prescriptions, public.consultation_prescription_items IN SHARE ROW EXCLUSIVE MODE;
CREATE TEMP TABLE _history_payload(data jsonb) ON COMMIT DROP;
INSERT INTO _history_payload VALUES (__PAYLOAD__::jsonb);
CREATE TEMP TABLE _history_legacy(data jsonb) ON COMMIT DROP;
INSERT INTO _history_legacy SELECT value FROM jsonb_array_elements(__LEGACY__::jsonb);

DO $seed$
DECLARE p jsonb; v jsonb; m jsonb; r jsonb; d public.doctors%rowtype; b public.pharmacy_brands%rowtype;
        a public.appointments%rowtype; pos integer; old_count integer;
BEGIN
 IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public'
    AND table_name='appointments' AND column_name='linked_appointment_id') THEN
   RAISE EXCEPTION 'Apply phase_6_followups_reports.sql before this seed.';
 END IF;
 -- Fail before retiring older fixtures if a required catalogue entry is absent.
 FOR v IN SELECT value FROM _history_payload,jsonb_array_elements(data->'visits') LOOP
   PERFORM 1 FROM public.doctors WHERE doctor_code=v->>'doctor_code' AND is_synthetic;
   IF NOT FOUND THEN RAISE EXCEPTION 'Missing synthetic doctor: %',v->>'doctor_code'; END IF;
   FOR m IN SELECT value FROM jsonb_array_elements(v->'medicines') LOOP
     PERFORM 1 FROM public.pharmacy_brands WHERE brand_id=m->>'brand_id' AND medicine_id=m->>'medicine_id';
     IF NOT FOUND THEN RAISE EXCEPTION 'Missing expected medicine/brand: %',m->>'brand_id'; END IF;
   END LOOP;
 END LOOP;
 FOR p IN SELECT value FROM _history_payload,jsonb_array_elements(data->'patients') LOOP
   IF EXISTS (SELECT 1 FROM public.patients WHERE id=(p->>'id')::uuid AND
      (phone IS DISTINCT FROM p->>'phone' OR email IS DISTINCT FROM p->>'email' OR role<>'patient')) THEN
     RAISE EXCEPTION 'Demo patient identity changed; refusing to overwrite it.';
   END IF;
   IF EXISTS (SELECT 1 FROM public.patients WHERE id<>(p->>'id')::uuid AND (phone=p->>'phone' OR email=p->>'email')) THEN
     RAISE EXCEPTION 'Phone/email already belongs to another patient; seed aborted.';
   END IF;
   INSERT INTO public.patients(id,full_name,phone,email,date_of_birth,age,gender,city,role)
   VALUES ((p->>'id')::uuid,p->>'full_name',p->>'phone',p->>'email',(p->>'date_of_birth')::date,
           extract(year from age(current_date,(p->>'date_of_birth')::date)),p->>'gender',p->>'city','patient')
   ON CONFLICT(id) DO NOTHING;
 END LOOP;
 -- Recognise exactly the ten original fixture rows, never a broad phone/date deletion.
 IF EXISTS (SELECT 1 FROM public.appointments a JOIN _history_legacy l ON a.id=(l.data->>'id')::uuid WHERE
    a.patient_id<>(l.data->>'patient_id')::uuid OR a.slot_id<>(l.data->>'slot_id')::uuid OR
    a.status<>'COMPLETED' OR a.idempotency_key<>'demo-history-v1/'||a.id::text OR
    a.finalised_record_key IS DISTINCT FROM 'demo_patient_history/v1/'||a.id::text||'/signed.json') THEN
   RAISE EXCEPTION 'Legacy IDs contain changed/non-demo history; refusing replacement.';
 END IF;
 IF EXISTS (SELECT 1 FROM public.appointments a WHERE a.linked_appointment_id IN
   (SELECT (data->>'id')::uuid FROM _history_legacy) AND a.id NOT IN (SELECT (data->>'id')::uuid FROM _history_legacy))
 OR EXISTS (SELECT 1 FROM public.emergency_intakes WHERE linked_appointment_id IN (SELECT (data->>'id')::uuid FROM _history_legacy)) THEN
   RAISE EXCEPTION 'Newer visits/intakes depend on legacy history; preserve those links and review manually.';
 END IF;
 IF EXISTS (SELECT 1 FROM public.pharmacy_reservations WHERE appointment_id IN (SELECT (data->>'id')::uuid FROM _history_legacy))
 OR EXISTS (SELECT 1 FROM public.consultation_jobs WHERE appointment_id IN (SELECT (data->>'id')::uuid FROM _history_legacy))
 OR EXISTS (SELECT 1 FROM public.consultation_recordings WHERE appointment_id IN (SELECT (data->>'id')::uuid FROM _history_legacy)) THEN
   RAISE EXCEPTION 'Legacy demo visits have stock/processing/recording activity; refusing replacement.';
 END IF;
 IF EXISTS (SELECT 1 FROM public.consultation_reports r JOIN _history_legacy l ON r.appointment_id=(l.data->>'id')::uuid
    WHERE NOT (l.data->'reports' ? r.id::text) OR r.is_synthetic IS NOT TRUE
       OR r.object_key NOT LIKE 'demo_patient_history/v1/%' OR r.content_type IS NOT NULL) THEN
   RAISE EXCEPTION 'Legacy demo visits have additional/changed reports; refusing replacement.';
 END IF;
 SELECT count(*) INTO old_count FROM public.appointments WHERE id IN (SELECT (data->>'id')::uuid FROM _history_legacy);
 DELETE FROM public.consultation_prescription_items WHERE appointment_id IN (SELECT (data->>'id')::uuid FROM _history_legacy);
 DELETE FROM public.consultation_prescriptions WHERE appointment_id IN (SELECT (data->>'id')::uuid FROM _history_legacy);
 DELETE FROM public.consultation_reports WHERE appointment_id IN (SELECT (data->>'id')::uuid FROM _history_legacy);
 DELETE FROM public.appointments WHERE id IN (SELECT (data->>'id')::uuid FROM _history_legacy);
 DELETE FROM public.slots s WHERE s.id IN (SELECT (data->>'slot_id')::uuid FROM _history_legacy)
   AND NOT EXISTS (SELECT 1 FROM public.appointments WHERE slot_id=s.id);
 RAISE NOTICE 'Retired % known v1 demo appointments; existing patient/Auth identities retained.',old_count;

 -- Parents precede children in the source; database follow-up guards remain enabled.
 FOR v IN SELECT value FROM _history_payload,jsonb_array_elements(data->'visits') LOOP
   SELECT * INTO STRICT d FROM public.doctors WHERE doctor_code=v->>'doctor_code' AND is_synthetic;
   INSERT INTO public.slots(id,doctor_id,starts_at,ends_at,status)
   VALUES ((v->>'slot_id')::uuid,d.id,(v->>'starts_at')::timestamptz,(v->>'completed_at')::timestamptz,'BOOKED') ON CONFLICT(id) DO NOTHING;
   IF NOT EXISTS (SELECT 1 FROM public.slots WHERE id=(v->>'slot_id')::uuid AND doctor_id=d.id
      AND starts_at=(v->>'starts_at')::timestamptz AND ends_at=(v->>'completed_at')::timestamptz AND status='BOOKED') THEN
     RAISE EXCEPTION 'Existing v2 slot changed; seed aborted.';
   END IF;
   INSERT INTO public.appointments(id,slot_id,patient_id,status,idempotency_key,reason,severity,symptoms,symptom_text,
     specialty_id,consent_recorded,created_at,started_at,completed_at,linked_appointment_id,transcript_key,soap_draft_key,finalised_record_key)
   VALUES ((v->>'id')::uuid,(v->>'slot_id')::uuid,(v->>'patient_id')::uuid,'COMPLETED','demo-history-v2/'||(v->>'id'),
     v->>'reason',v->>'severity',v->'symptoms',v->>'symptom_text',d.specialty_id,true,(v->>'created_at')::timestamptz,
     (v->>'starts_at')::timestamptz,(v->>'completed_at')::timestamptz,(v->>'linked_appointment_id')::uuid,
     v->>'transcript_key',v->>'soap_draft_key',v->>'finalised_record_key') ON CONFLICT(id) DO NOTHING;
   SELECT * INTO STRICT a FROM public.appointments WHERE id=(v->>'id')::uuid;
   IF (a.slot_id,a.patient_id,a.status,a.idempotency_key,a.reason,a.severity,a.symptoms,a.symptom_text,a.specialty_id,
       a.consent_recorded,a.created_at,a.started_at,a.completed_at,a.linked_appointment_id,a.transcript_key,a.soap_draft_key,a.finalised_record_key)
      IS DISTINCT FROM ((v->>'slot_id')::uuid,(v->>'patient_id')::uuid,'COMPLETED'::text,'demo-history-v2/'||(v->>'id'),
       v->>'reason',v->>'severity',v->'symptoms',v->>'symptom_text',d.specialty_id,true,(v->>'created_at')::timestamptz,
       (v->>'starts_at')::timestamptz,(v->>'completed_at')::timestamptz,(v->>'linked_appointment_id')::uuid,
       v->>'transcript_key',v->>'soap_draft_key',v->>'finalised_record_key') THEN
     RAISE EXCEPTION 'Existing v2 appointment changed; seed aborted.';
   END IF;
   INSERT INTO public.consultation_prescriptions(appointment_id,doctor_id,active,soap_revision,soap_draft_key,reviewed_at,updated_at)
   VALUES(a.id,d.id,false,v->>'soap_revision',a.soap_draft_key,a.completed_at,a.completed_at) ON CONFLICT(appointment_id) DO NOTHING;
   IF NOT EXISTS (SELECT 1 FROM public.consultation_prescriptions WHERE appointment_id=a.id AND doctor_id=d.id AND NOT active
      AND soap_revision=v->>'soap_revision' AND soap_draft_key=a.soap_draft_key AND reviewed_at=a.completed_at) THEN
     RAISE EXCEPTION 'Existing v2 prescription review changed; seed aborted.';
   END IF;
   pos:=0;
   FOR m IN SELECT value FROM jsonb_array_elements(v->'medicines') LOOP
     SELECT * INTO STRICT b FROM public.pharmacy_brands WHERE brand_id=m->>'brand_id' AND medicine_id=m->>'medicine_id';
     INSERT INTO public.consultation_prescription_items(appointment_id,brand_id,medicine_id,position,quantity,strength_form,dose,frequency,duration,instructions,details)
     VALUES(a.id,b.brand_id,b.medicine_id,pos,(m->>'quantity')::integer,m->>'strength_form',m->>'dose',m->>'frequency',m->>'duration',
       m->>'instructions',jsonb_build_object('brand',b.brand,'variant',b.variant,'manufacturer',b.manufacturer,'is_synthetic',true))
     ON CONFLICT(appointment_id,brand_id) DO NOTHING;
     IF NOT EXISTS (SELECT 1 FROM public.consultation_prescription_items WHERE appointment_id=a.id AND brand_id=b.brand_id
       AND medicine_id=b.medicine_id AND position=pos AND quantity=(m->>'quantity')::integer AND strength_form=m->>'strength_form'
       AND dose=m->>'dose' AND frequency=m->>'frequency' AND duration=m->>'duration' AND instructions=m->>'instructions') THEN
       RAISE EXCEPTION 'Existing v2 medicine instructions changed; seed aborted.';
     END IF;
     pos:=pos+1;
   END LOOP;
   IF (SELECT count(*) FROM public.consultation_prescription_items WHERE appointment_id=a.id)<>pos THEN
     RAISE EXCEPTION 'Existing v2 prescription has unexpected items; seed aborted.';
   END IF;
   FOR r IN SELECT value FROM jsonb_array_elements(v->'reports') LOOP
     INSERT INTO public.consultation_reports(id,appointment_id,report_type,title,findings,object_key,reported_at,is_synthetic,content_type,size_bytes)
     VALUES((r->>'id')::uuid,a.id,r->>'type',r->>'title',r,r->>'object_key',(r->>'reported_at')::timestamptz,true,
       r->>'content_type',(r->>'size_bytes')::integer) ON CONFLICT(id) DO NOTHING;
     IF NOT EXISTS (SELECT 1 FROM public.consultation_reports WHERE id=(r->>'id')::uuid AND appointment_id=a.id
       AND findings=r AND object_key=r->>'object_key' AND content_type='application/pdf' AND is_synthetic) THEN
       RAISE EXCEPTION 'Existing v2 report changed; seed aborted.';
     END IF;
   END LOOP;
 END LOOP;
END $seed$;
DROP TABLE _history_payload, _history_legacy;
NOTIFY pgrst,'reload schema';
COMMIT;
