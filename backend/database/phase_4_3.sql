-- Phase 4.3: signing and inventory reservations are one transaction.
-- Requires Phase 4.1. Does not reserve stock retroactively for older signed visits.
begin;
alter table public.pharmacy_brands add column if not exists locked_quantity integer not null default 0;
alter table public.pharmacy_brands add column if not exists available_quantity integer
  generated always as (stock_quantity - locked_quantity) stored;
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'pharmacy_stock_reservation_bounds'
                 and conrelid = 'public.pharmacy_brands'::regclass) then
    alter table public.pharmacy_brands add constraint pharmacy_stock_reservation_bounds
      check (locked_quantity >= 0 and (locked_quantity = 0 or stock_quantity >= locked_quantity)
             and (stock_quantity is not null or locked_quantity = 0));
  end if;
end $$;
create table if not exists public.pharmacy_reservations (
  appointment_id uuid not null references public.appointments(id),
  brand_id text not null references public.pharmacy_brands(brand_id),
  quantity integer not null check (quantity > 0),
  status text not null default 'LOCKED' check (status in ('LOCKED','RELEASED','DISPENSED')),
  created_at timestamptz not null default now(),
  resolved_at timestamptz,
  resolved_by uuid references public.pharmacists(id),
  primary key (appointment_id, brand_id)
);
create index if not exists pharmacy_reservations_status_idx on public.pharmacy_reservations(status, created_at);
alter table public.pharmacy_reservations enable row level security;
revoke all on public.pharmacy_reservations from anon, authenticated;
grant all on public.pharmacy_reservations to service_role;

create or replace function public.finalize_consultation_with_stock(
  p_appointment_id uuid, p_doctor_id uuid, p_record_key text, p_prescription jsonb
) returns jsonb language plpgsql set search_path = public as $$
declare
  visit public.appointments%rowtype;
  stock public.pharmacy_brands%rowtype;
  item jsonb;
  units integer;
begin
  select * into visit from public.appointments where id = p_appointment_id for update;
  if not found or not exists (select 1 from public.slots where id = visit.slot_id and doctor_id = p_doctor_id) then
    raise exception using errcode = 'P0001', message = 'Consultation does not belong to this doctor.';
  end if;
  if visit.status = 'COMPLETED' then return to_jsonb(visit); end if;
  if visit.status <> 'IN_PROGRESS' or visit.consent_recorded is not true then
    raise exception using errcode = 'P0001', message = 'Start the consultation with consent before signing.';
  end if;
  if nullif(p_record_key, '') is null or p_prescription is null or jsonb_typeof(p_prescription) <> 'array' then
    raise exception using errcode = 'P0001', message = 'A signed snapshot and prescription are required.';
  end if;
  if jsonb_array_length(p_prescription) > 30 or
     (select count(*) <> count(distinct e->>'brand_id') from jsonb_array_elements(p_prescription) e) then
    raise exception using errcode = 'P0001', message = 'Invalid or duplicate prescription items.';
  end if;
  -- All signing and release operations lock brands in the same order.
  for item in select value from jsonb_array_elements(p_prescription) order by value->>'brand_id' loop
    if coalesce(item->>'quantity', '') !~ '^[0-9]{1,7}$' then
      raise exception using errcode = 'P0001', message = 'Enter a positive whole stock quantity for every medicine.';
    end if;
    units := (item->>'quantity')::integer;
    if units < 1 or units > 1000000 then
      raise exception using errcode = 'P0001', message = 'Medicine stock quantity is outside the allowed range.';
    end if;
    select * into stock from public.pharmacy_brands where brand_id = item->>'brand_id' for update;
    if not found then
      raise exception using errcode = 'P0001', message = 'A prescribed medicine is no longer in the pharmacy catalogue.';
    end if;
    if stock.stock_quantity is null or stock.stock_quantity - stock.locked_quantity < units then
      raise exception using errcode = 'P0001', message = 'Insufficient available stock for ' || stock.brand || '. Review the prescription and retry.';
    end if;
    update public.pharmacy_brands set locked_quantity = locked_quantity + units where brand_id = stock.brand_id;
    insert into public.pharmacy_reservations(appointment_id, brand_id, quantity)
      values (p_appointment_id, stock.brand_id, units);
  end loop;
  update public.appointments set status = 'COMPLETED', completed_at = now(), finalised_record_key = p_record_key
    where id = p_appointment_id returning * into visit;
  return to_jsonb(visit);
end $$;

create or replace function public.resolve_pharmacy_reservation(
  p_appointment_id uuid, p_pharmacist_id uuid, p_action text
) returns jsonb language plpgsql set search_path = public as $$
declare
  visit public.appointments%rowtype;
  reservation public.pharmacy_reservations%rowtype;
  target_status text;
begin
  if not exists (select 1 from public.pharmacists where id = p_pharmacist_id and is_active) then
    raise exception using errcode = 'P0001', message = 'Active pharmacist not found.';
  end if;
  if p_action not in ('release','dispense') or p_action is null then
    raise exception using errcode = 'P0001', message = 'Unknown pharmacy action.';
  end if;
  target_status := case when p_action = 'release' then 'RELEASED' else 'DISPENSED' end;
  select * into visit from public.appointments where id = p_appointment_id for update;
  if not found or visit.status <> 'COMPLETED' then
    raise exception using errcode = 'P0001', message = 'Completed consultation not found.';
  end if;
  if not exists (select 1 from public.pharmacy_reservations where appointment_id = p_appointment_id) then
    raise exception using errcode = 'P0001', message = 'This consultation has no stock reservation.';
  end if;
  if not exists (select 1 from public.pharmacy_reservations where appointment_id = p_appointment_id and status <> target_status) then
    return jsonb_build_object('status', target_status); -- safe retry
  end if;
  if exists (select 1 from public.pharmacy_reservations where appointment_id = p_appointment_id and status <> 'LOCKED') then
    raise exception using errcode = 'P0001', message = 'This reservation has already been resolved. Refresh the consultation.';
  end if;
  if p_action = 'release' and (visit.completed_at is null or now() < visit.completed_at + interval '24 hours') then
    raise exception using errcode = 'P0001', message = 'Stock can only be unlocked 24 hours after signing.';
  end if;
  for reservation in select * from public.pharmacy_reservations where appointment_id = p_appointment_id order by brand_id for update loop
    -- Decrement physical stock only when the patient collects the medicines.
    update public.pharmacy_brands set
      stock_quantity = stock_quantity - case when p_action = 'dispense' then reservation.quantity else 0 end,
      locked_quantity = locked_quantity - reservation.quantity,
      stock_updated_at = now()
      where brand_id = reservation.brand_id;
  end loop;
  update public.pharmacy_reservations set status = target_status, resolved_at = now(), resolved_by = p_pharmacist_id
    where appointment_id = p_appointment_id;
  return jsonb_build_object('status', target_status);
end $$;

revoke all on function public.finalize_consultation_with_stock(uuid,uuid,text,jsonb) from public, anon, authenticated;
grant execute on function public.finalize_consultation_with_stock(uuid,uuid,text,jsonb) to service_role;
revoke all on function public.resolve_pharmacy_reservation(uuid,uuid,text) from public, anon, authenticated;
grant execute on function public.resolve_pharmacy_reservation(uuid,uuid,text) to service_role;
notify pgrst, 'reload schema';
commit;
