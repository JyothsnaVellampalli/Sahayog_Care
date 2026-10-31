-- Add explicit medicine identity without changing brand-level inventory locking.
begin;
alter table public.pharmacy_reservations add column if not exists medicine_id text;
update public.pharmacy_reservations r set medicine_id=b.medicine_id
  from public.pharmacy_brands b where b.brand_id=r.brand_id and r.medicine_id is null;
alter table public.pharmacy_reservations alter column medicine_id set not null;
create unique index if not exists pharmacy_brands_brand_medicine_unique
  on public.pharmacy_brands(brand_id,medicine_id);
do $$ begin
  if not exists(select 1 from pg_constraint where conname='reservation_brand_medicine_fk'
      and conrelid='public.pharmacy_reservations'::regclass) then
    alter table public.pharmacy_reservations add constraint reservation_brand_medicine_fk
      foreign key(brand_id,medicine_id) references public.pharmacy_brands(brand_id,medicine_id);
    alter table public.pharmacy_reservations add constraint reservation_medicine_fk
      foreign key(medicine_id) references public.pharmacy_medicines(id);
  end if;
end $$;
create or replace function public.set_reservation_medicine() returns trigger
language plpgsql set search_path=public as $$
begin
  if new.medicine_id is null then
    select medicine_id into new.medicine_id from public.pharmacy_brands where brand_id=new.brand_id;
  end if;
  return new;
end $$;
drop trigger if exists set_reservation_medicine on public.pharmacy_reservations;
create trigger set_reservation_medicine before insert or update of brand_id,medicine_id
  on public.pharmacy_reservations for each row execute function public.set_reservation_medicine();
notify pgrst,'reload schema';
commit;
