-- Additive Phase 4.1 schema. Requires the Phase 3 appointments contract.
begin;
create table if not exists public.pharmacists (
  id uuid primary key default gen_random_uuid(),
  full_name text not null,
  phone text not null unique,
  is_active boolean not null default true
);
create table if not exists public.pharmacy_medicines (
  id text primary key,
  generic_name text not null,
  specialty text not null check (specialty in ('cardiology','orthopedics','dermatology','gastroenterology')),
  composition text not null,
  source_details jsonb not null
);
create table if not exists public.pharmacy_brands (
  brand_id text primary key,
  medicine_id text not null references public.pharmacy_medicines(id),
  brand text not null,
  manufacturer text,
  variant text not null,
  source_status text not null check (source_status in ('web_confirmed','unverified')),
  stock_quantity integer check (stock_quantity >= 0),
  stock_is_demo boolean not null default true,
  stock_updated_at timestamptz
);
create index if not exists pharmacy_brands_medicine_idx on public.pharmacy_brands(medicine_id);
alter table public.pharmacists enable row level security;
alter table public.pharmacy_medicines enable row level security;
alter table public.pharmacy_brands enable row level security;
revoke all on public.pharmacists, public.pharmacy_medicines, public.pharmacy_brands from anon, authenticated;
grant all on public.pharmacists, public.pharmacy_medicines, public.pharmacy_brands to service_role;
-- Development-stage phone lookup, matching the doctor portal. No auth token.
insert into public.pharmacists(full_name, phone)
values ('Demo Pharmacist', '+919800000001') on conflict (phone) do nothing;
notify pgrst, 'reload schema';
commit;
