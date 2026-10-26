create table if not exists public.patients (
  id            uuid primary key default gen_random_uuid(),
  date_of_birth date check (date_of_birth <= current_date and date_of_birth >= '1900-01-01'),
  gender        text check (gender in ('female', 'male', 'other', 'prefer_not_to_say')),
  city          text check (city in ('Pune', 'Hyderabad')),
  created_at    timestamptz not null default now()
);

create table if not exists public.appointments (
  id              uuid primary key default gen_random_uuid(),
  slot_id         uuid not null references public.slots(id),
  patient_id      uuid not null references public.patients(id),
  status          text not null default 'BOOKED'
                  check (status in ('BOOKED', 'CANCELLED', 'COMPLETED', 'NO_SHOW')),
  idempotency_key text not null unique,
  created_at      timestamptz not null default now()
);

create unique index if not exists appointments_one_active_per_slot
  on public.appointments (slot_id) where status = 'BOOKED'

insert into public.doctors
  (doctor_code, full_name, specialty_id, facility_id, languages, years_experience)
select v.doctor_code,
       v.full_name,
       s.id,
       f.id,
       v.languages::text[],
       v.years_experience
  from (values
    -- Cardiology
    ('CARD-01', 'Dr. Ananya Rao',          'CARD', 'SH-PUNE-C01', '{English,Hindi}',     14),
    ('CARD-02', 'Dr. Vikram Deshmukh',     'CARD', 'SH-HYD-C01',  '{English,Telugu}',    11),
    ('CARD-03', 'Dr. Sneha Iyer',          'CARD', 'SH-PUNE-C02', '{English,Marathi}',    9),
    ('CARD-04', 'Dr. Rahul Krishnan',      'CARD', 'SH-HYD-C02',  '{English,Tamil}',     18),
    ('CARD-05', 'Dr. Meera Joshi',         'CARD', 'SH-PUNE-C03', '{English,Marathi}',    7),
    -- Neurology
    ('NEUR-01', 'Dr. Arjun Nair',          'NEUR', 'SH-HYD-C03',  '{English,Malayalam}', 13),
    ('NEUR-02', 'Dr. Priya Kulkarni',      'NEUR', 'SH-PUNE-C04', '{English,Marathi}',   10),
    ('NEUR-03', 'Dr. Sameer Patil',        'NEUR', 'SH-PUNE-C05', '{English,Hindi}',     16),
    ('NEUR-04', 'Dr. Lakshmi Reddy',       'NEUR', 'SH-HYD-C04',  '{English,Telugu}',     8),
    ('NEUR-05', 'Dr. Karan Mehta',         'NEUR', 'SH-HYD-C05',  '{English,Hindi}',     12),
    -- Gastroenterology
    ('GAST-01', 'Dr. Nisha Verma',         'GAST', 'SH-PUNE-C06', '{English,Hindi}',     15),
    ('GAST-02', 'Dr. Aditya Pillai',       'GAST', 'SH-HYD-C06',  '{English,Malayalam}',  9),
    ('GAST-03', 'Dr. Ritu Saxena',         'GAST', 'SH-PUNE-C07', '{English,Hindi}',     11),
    ('GAST-04', 'Dr. Suresh Naidu',        'GAST', 'SH-HYD-C07',  '{English,Telugu}',    20),
    ('GAST-05', 'Dr. Pooja Shetty',        'GAST', 'SH-HYD-C08',  '{English,Kannada}',    6),
    -- Orthopaedics
    ('ORTH-01', 'Dr. Harish Gowda',        'ORTH', 'SH-HYD-C09',  '{English,Kannada}',   17),
    ('ORTH-02', 'Dr. Kavya Menon',         'ORTH', 'SH-PUNE-C08', '{English,Malayalam}',  9),
    ('ORTH-03', 'Dr. Rohan Bhatt',         'ORTH', 'SH-PUNE-C09', '{English,Gujarati}',  12),
    ('ORTH-04', 'Dr. Divya Chandran',      'ORTH', 'SH-HYD-C10',  '{English,Tamil}',      8),
    ('ORTH-05', 'Dr. Manoj Tiwari',        'ORTH', 'SH-PUNE-C10', '{English,Hindi}',     19),
    -- Dermatology
    ('DERM-01', 'Dr. Tara Fernandes',      'DERM', 'SH-PUNE-C11', '{English,Konkani}',   10),
    ('DERM-02', 'Dr. Imran Sheikh',        'DERM', 'SH-HYD-C11',  '{English,Urdu}',       7),
    ('DERM-03', 'Dr. Ishita Banerjee',     'DERM', 'SH-HYD-C01',  '{English,Bengali}',   13),
    ('DERM-04', 'Dr. Gaurav Kapoor',       'DERM', 'SH-PUNE-C01', '{English,Hindi}',      9),
    ('DERM-05', 'Dr. Sunita Ghosh',        'DERM', 'SH-PUNE-C02', '{English,Bengali}',   15),
    -- Pulmonology
    ('PULM-01', 'Dr. Anil Varma',          'PULM', 'SH-HYD-C02',  '{English,Hindi}',     16),
    ('PULM-02', 'Dr. Shreya Bose',         'PULM', 'SH-PUNE-C03', '{English,Bengali}',    8),
    ('PULM-03', 'Dr. Naveen Kumar',        'PULM', 'SH-HYD-C03',  '{English,Telugu}',    11),
    ('PULM-04', 'Dr. Farah Qureshi',       'PULM', 'SH-PUNE-C04', '{English,Urdu}',       6),
    ('PULM-05', 'Dr. Girish Hegde',        'PULM', 'SH-HYD-C04',  '{English,Kannada}',   14),
    -- Endocrinology
    ('ENDO-01', 'Dr. Madhuri Sawant',      'ENDO', 'SH-PUNE-C05', '{English,Marathi}',   12),
    ('ENDO-02', 'Dr. Prakash Rangan',      'ENDO', 'SH-HYD-C05',  '{English,Tamil}',     18),
    ('ENDO-03', 'Dr. Ankita Dutta',        'ENDO', 'SH-HYD-C06',  '{English,Bengali}',    7),
    ('ENDO-04', 'Dr. Rajesh Iyengar',      'ENDO', 'SH-PUNE-C06', '{English,Kannada}',   10),
    ('ENDO-05', 'Dr. Neha Chopra',         'ENDO', 'SH-PUNE-C07', '{English,Hindi}',      9),
    -- General Medicine
    ('GMED-01', 'Dr. Vandana Shah',        'GMED', 'SH-PUNE-C08', '{English,Gujarati}',  20),
    ('GMED-02', 'Dr. Abhishek Pandey',     'GMED', 'SH-HYD-C07',  '{English,Hindi}',      9),
    ('GMED-03', 'Dr. Lata Krishnaswamy',   'GMED', 'SH-HYD-C08',  '{English,Tamil}',     14),
    ('GMED-04', 'Dr. Deepak Malhotra',     'GMED', 'SH-PUNE-C09', '{English,Hindi}',     11),
    ('GMED-05', 'Dr. Revathi Subramanian', 'GMED', 'SH-HYD-C09',  '{English,Tamil}',     13)
  ) as v(doctor_code, full_name, specialty_code, facility_code, languages, years_experience)
  join public.specialties s on s.code = v.specialty_code
  join public.hospitals   f on f.code = v.facility_code
on conflict (doctor_code) do nothing;
 

insert into public.specialties (code, name, description) values
  ('CARD', 'Cardiology',       'Heart and blood vessel conditions'),
  ('NEUR', 'Neurology',        'Brain, spinal cord and nerve conditions'),
  ('GAST', 'Gastroenterology', 'Stomach, intestine, liver and pancreas'),
  ('ORTH', 'Orthopaedics',     'Bones, joints, muscles and ligaments'),
  ('DERM', 'Dermatology',      'Skin, hair and nail conditions'),
  ('PULM', 'Pulmonology',      'Lungs and breathing conditions'),
  ('ENDO', 'Endocrinology',    'Hormones, thyroid, diabetes and metabolism'),
  ('GMED', 'General Medicine', 'General adult medical care and first review')
on conflict (code) do nothing;


insert into public.hospitals (code, name, facility_type, city, is_synthetic) values
  ('SH-PUNE-H1', 'Sahyog Hospital Kothrud (synthetic)',       'HOSPITAL', 'Pune',      true),
  ('SH-PUNE-H2', 'Sahyog Hospital Hadapsar (synthetic)',      'HOSPITAL', 'Pune',      true),
  ('SH-PUNE-H3', 'Sahyog Hospital Baner (synthetic)',         'HOSPITAL', 'Pune',      true),
  ('SH-HYD-H1',  'Sahyog Hospital Banjara Hills (synthetic)', 'HOSPITAL', 'Hyderabad', true),
  ('SH-HYD-H2',  'Sahyog Hospital Gachibowli (synthetic)',    'HOSPITAL', 'Hyderabad', true),
  ('SH-HYD-H3',  'Sahyog Hospital Kukatpally (synthetic)',    'HOSPITAL', 'Hyderabad', true)
on conflict (code) do nothing;



insert into public.hospitals
  (code, name, facility_type, city, parent_hospital_id, is_synthetic)
select v.code, v.name, 'CLINIC', v.city, p.id, true
  from (values
    ('SH-PUNE-C01', 'Sahyog Clinic Shivajinagar (synthetic)',    'Pune',      'SH-PUNE-H1'),
    ('SH-PUNE-C02', 'Sahyog Clinic Aundh (synthetic)',           'Pune',      'SH-PUNE-H1'),
    ('SH-PUNE-C03', 'Sahyog Clinic Viman Nagar (synthetic)',     'Pune',      'SH-PUNE-H1'),
    ('SH-PUNE-C04', 'Sahyog Clinic Warje (synthetic)',           'Pune',      'SH-PUNE-H1'),
    ('SH-PUNE-C05', 'Sahyog Clinic Hadapsar Camp (synthetic)',   'Pune',      'SH-PUNE-H2'),
    ('SH-PUNE-C06', 'Sahyog Clinic Magarpatta (synthetic)',      'Pune',      'SH-PUNE-H2'),
    ('SH-PUNE-C07', 'Sahyog Clinic Kharadi (synthetic)',         'Pune',      'SH-PUNE-H2'),
    ('SH-PUNE-C08', 'Sahyog Clinic Pimpri (synthetic)',          'Pune',      'SH-PUNE-H2'),
    ('SH-PUNE-C09', 'Sahyog Clinic Baner Road (synthetic)',      'Pune',      'SH-PUNE-H3'),
    ('SH-PUNE-C10', 'Sahyog Clinic Wakad (synthetic)',           'Pune',      'SH-PUNE-H3'),
    ('SH-PUNE-C11', 'Sahyog Clinic Hinjewadi (synthetic)',       'Pune',      'SH-PUNE-H3'),
    ('SH-HYD-C01',  'Sahyog Clinic Jubilee Hills (synthetic)',   'Hyderabad', 'SH-HYD-H1'),
    ('SH-HYD-C02',  'Sahyog Clinic Somajiguda (synthetic)',      'Hyderabad', 'SH-HYD-H1'),
    ('SH-HYD-C03',  'Sahyog Clinic Himayatnagar (synthetic)',    'Hyderabad', 'SH-HYD-H1'),
    ('SH-HYD-C04',  'Sahyog Clinic Begumpet (synthetic)',        'Hyderabad', 'SH-HYD-H1'),
    ('SH-HYD-C05',  'Sahyog Clinic Madhapur (synthetic)',        'Hyderabad', 'SH-HYD-H2'),
    ('SH-HYD-C06',  'Sahyog Clinic Kondapur (synthetic)',        'Hyderabad', 'SH-HYD-H2'),
    ('SH-HYD-C07',  'Sahyog Clinic Hitech City (synthetic)',     'Hyderabad', 'SH-HYD-H2'),
    ('SH-HYD-C08',  'Sahyog Clinic Miyapur (synthetic)',         'Hyderabad', 'SH-HYD-H2'),
    ('SH-HYD-C09',  'Sahyog Clinic KPHB Colony (synthetic)',     'Hyderabad', 'SH-HYD-H3'),
    ('SH-HYD-C10',  'Sahyog Clinic Kukatpally Housing (synthetic)', 'Hyderabad', 'SH-HYD-H3'),
    ('SH-HYD-C11',  'Sahyog Clinic Bachupally (synthetic)',      'Hyderabad', 'SH-HYD-H3')
  ) as v(code, name, city, parent_code)
  join public.hospitals p on p.code = v.parent_code
on conflict (code) do nothing;

create table if not exists public.specialties (
  id          uuid primary key default gen_random_uuid(),
  code        text not null unique,
  name        text not null,
  description text,
  created_at  timestamptz not null default now()
);

create table if not exists public.hospitals (
  id                 uuid primary key default gen_random_uuid(),
  code               text not null unique,
  name               text not null,
  facility_type      text not null check (facility_type in ('HOSPITAL', 'CLINIC')),
  city               text not null check (city in ('Pune', 'Hyderabad')),
  parent_hospital_id uuid references public.hospitals(id),
  is_synthetic       boolean not null default true,
  created_at         timestamptz not null default now(),
  constraint facility_parent_rule check (
    (facility_type = 'HOSPITAL' and parent_hospital_id is null) or
    (facility_type = 'CLINIC'   and parent_hospital_id is not null)
  )
);

create table if not exists public.doctors (
  id               uuid primary key default gen_random_uuid(),
  doctor_code      text not null unique,
  full_name        text not null,
  specialty_id     uuid not null references public.specialties(id),
  facility_id      uuid not null references public.hospitals(id),
  languages        text[] not null default array['English'],
  years_experience int  not null default 0 check (years_experience >= 0),
  is_active        boolean not null default true,
  is_synthetic     boolean not null default true,
  created_at       timestamptz not null default now()
);

create index if not exists doctors_specialty_idx
  on public.doctors (specialty_id) where is_active;


create table if not exists public.doctor_availability (
  id           uuid primary key default gen_random_uuid(),
  doctor_id    uuid not null references public.doctors(id) on delete cascade,
  weekday      smallint check (weekday between 0 and 6),
  on_date      date,
  start_time   time not null,
  end_time     time not null,
  slot_minutes int  not null default 45 check (slot_minutes between 15 and 120),
  is_active    boolean not null default true,
  constraint availability_time_order check (end_time > start_time),
  constraint availability_kind check (
    (on_date is null and weekday is not null) or
    (on_date is not null and weekday is null)
  ),
  constraint availability_unique_weekly unique (doctor_id, weekday, start_time),
  constraint availability_unique_date   unique (doctor_id, on_date, start_time)
);


create table if not exists public.slots (
  id              uuid primary key default gen_random_uuid(),
  doctor_id       uuid not null references public.doctors(id) on delete cascade,
  availability_id uuid references public.doctor_availability(id) on delete set null,
  starts_at       timestamptz not null,
  ends_at         timestamptz not null,
  status          text not null default 'OPEN'
                  check (status in ('OPEN', 'BOOKED', 'BLOCKED')),
  constraint slots_time_order check (ends_at > starts_at),
  constraint slots_unique_start unique (doctor_id, starts_at)
);

create index if not exists slots_open_idx
  on public.slots (doctor_id, starts_at) where status = 'OPEN';

