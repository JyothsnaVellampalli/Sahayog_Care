-- Requires consultation_processing.sql and Phase 4.3. Additive; retains legacy objects.
begin;
create table if not exists public.consultation_prescriptions (
  appointment_id uuid primary key references public.appointments(id),
  doctor_id uuid references public.doctors(id),
  active boolean not null default true,
  soap_revision text,
  soap_draft_key text,
  reviewed_at timestamptz,
  updated_at timestamptz not null default now()
);
create table if not exists public.consultation_prescription_items (
  appointment_id uuid not null references public.consultation_prescriptions(appointment_id),
  brand_id text not null references public.pharmacy_brands(brand_id),
  medicine_id text not null references public.pharmacy_medicines(id),
  position integer not null,
  quantity integer check(quantity between 1 and 1000000),
  strength_form text not null default '', dose text not null default '',
  frequency text not null default '', duration text not null default '',
  instructions text not null default '',
  details jsonb not null default '{}',
  primary key(appointment_id,brand_id)
);
create table if not exists public.consultation_recordings (
  appointment_id uuid not null references public.appointments(id),
  recording_id uuid not null,
  provider_state jsonb not null,
  updated_at timestamptz not null default now(),
  primary key(appointment_id,recording_id)
);
alter table public.consultation_prescriptions enable row level security;
alter table public.consultation_prescription_items enable row level security;
alter table public.consultation_recordings enable row level security;
revoke all on public.consultation_prescriptions,public.consultation_prescription_items,public.consultation_recordings from anon,authenticated;
grant all on public.consultation_prescriptions,public.consultation_prescription_items,public.consultation_recordings to service_role;

create or replace function public.read_consultation_prescription(p_visit uuid)
returns jsonb language sql stable set search_path=public as $$
  select to_jsonb(p) || jsonb_build_object('items',coalesce((
    select jsonb_agg(i.details || jsonb_build_object(
      'brand_id',i.brand_id,'medicine_id',i.medicine_id,'quantity',i.quantity,
      'strength_form',i.strength_form,'dose',i.dose,'frequency',i.frequency,
      'duration',i.duration,'instructions',i.instructions) order by i.position)
    from public.consultation_prescription_items i where i.appointment_id=p_visit),'[]'::jsonb))
  from public.consultation_prescriptions p where p.appointment_id=p_visit;
$$;

create or replace function public.write_consultation_prescription(
  p_visit uuid,p_record jsonb,p_workspace boolean,p_import boolean default false)
returns jsonb language plpgsql set search_path=public as $$
declare v public.appointments%rowtype; doctor uuid; item jsonb; b public.pharmacy_brands%rowtype; pos integer:=0;
begin
  select * into v from public.appointments where id=p_visit for update;
  if not found then raise exception 'Consultation not found.'; end if;
  if p_import and exists(select 1 from public.consultation_prescriptions where appointment_id=p_visit) then
    return public.read_consultation_prescription(p_visit);
  end if;
  if not p_import and v.status<>'IN_PROGRESS' then raise exception 'Consultation is not open.'; end if;
  select doctor_id into doctor from public.slots where id=v.slot_id;
  if not p_import and not p_workspace and
     ((p_record->>'doctor_id')::uuid is distinct from doctor or
      p_record->>'soap_draft_key' is distinct from v.soap_draft_key) then
    raise exception 'SOAP changed. Reload and review the prescription.';
  end if;
  if jsonb_typeof(p_record->'items') is distinct from 'array' or jsonb_array_length(p_record->'items')>30 then
    raise exception 'Invalid prescription items.';
  end if;
  insert into public.consultation_prescriptions(appointment_id,doctor_id,active,soap_revision,soap_draft_key,reviewed_at)
    values(p_visit,doctor,p_workspace,p_record->>'soap_revision',v.soap_draft_key,(p_record->>'reviewed_at')::timestamptz)
    on conflict(appointment_id) do update set active=excluded.active,soap_revision=excluded.soap_revision,
      soap_draft_key=excluded.soap_draft_key,reviewed_at=excluded.reviewed_at,updated_at=now();
  delete from public.consultation_prescription_items where appointment_id=p_visit;
  for item in select value from jsonb_array_elements(p_record->'items') loop
    select * into b from public.pharmacy_brands where brand_id=item->>'brand_id';
    if not found then raise exception 'Medicine is no longer in the catalogue.'; end if;
    if not p_workspace and not p_import and (nullif(item->>'quantity','') is null or
       nullif(trim(item->>'dose'),'') is null or nullif(trim(item->>'frequency'),'') is null or
       nullif(trim(item->>'duration'),'') is null or nullif(trim(item->>'strength_form'),'') is null) then
      raise exception 'Complete the prescription instructions before review.';
    end if;
    insert into public.consultation_prescription_items(appointment_id,brand_id,medicine_id,position,quantity,
      strength_form,dose,frequency,duration,instructions,details)
    values(p_visit,b.brand_id,b.medicine_id,pos,(item->>'quantity')::integer,
      coalesce(item->>'strength_form',''),coalesce(item->>'dose',''),coalesce(item->>'frequency',''),
      coalesce(item->>'duration',''),coalesce(item->>'instructions',''),
      (item - array['brand_id','medicine_id','quantity','strength_form','dose','frequency','duration','instructions']) ||
      jsonb_build_object('brand',b.brand,'variant',b.variant,'manufacturer',b.manufacturer));
    pos:=pos+1;
  end loop;
  return public.read_consultation_prescription(p_visit);
end $$;

-- Keep the existing stock transaction, adding a locked check against the reviewed DB prescription.
do $$ begin
  if to_regprocedure('public.finalize_consultation_stock_internal(uuid,uuid,text,jsonb)') is null then
    alter function public.finalize_consultation_with_stock(uuid,uuid,text,jsonb) rename to finalize_consultation_stock_internal;
  end if;
end $$;
create or replace function public.finalize_consultation_with_stock(
  p_appointment_id uuid,p_doctor_id uuid,p_record_key text,p_prescription jsonb)
returns jsonb language plpgsql set search_path=public as $$
declare v public.appointments%rowtype; rx jsonb;
begin
  select * into v from public.appointments where id=p_appointment_id for update;
  if v.status='COMPLETED' then
    return public.finalize_consultation_stock_internal(p_appointment_id,p_doctor_id,p_record_key,p_prescription);
  end if;
  rx:=public.read_consultation_prescription(p_appointment_id);
  if rx is null or (rx->>'active')::boolean or rx->>'reviewed_at' is null or
     rx->>'soap_draft_key' is distinct from v.soap_draft_key or
     rx->>'doctor_id' is distinct from p_doctor_id::text or rx->'items' is distinct from p_prescription then
    raise exception 'Prescription or SOAP changed. Reload and review before signing.';
  end if;
  return public.finalize_consultation_stock_internal(p_appointment_id,p_doctor_id,p_record_key,p_prescription);
end $$;
revoke all on function public.read_consultation_prescription(uuid),public.write_consultation_prescription(uuid,jsonb,boolean,boolean),
  public.finalize_consultation_with_stock(uuid,uuid,text,jsonb),public.finalize_consultation_stock_internal(uuid,uuid,text,jsonb) from public,anon,authenticated;
grant execute on function public.read_consultation_prescription(uuid),public.write_consultation_prescription(uuid,jsonb,boolean,boolean),
  public.finalize_consultation_with_stock(uuid,uuid,text,jsonb),public.finalize_consultation_stock_internal(uuid,uuid,text,jsonb) to service_role;
notify pgrst,'reload schema';
commit;
