-- Up in the Air: SFO flight week (2026-08-03..09) arrivals + departures with observed tracks.
-- Read-only public data. Writes happen only with the service-role key / DB owner (RLS bypass).

create table if not exists public.flights (
  operation_id      text primary key,
  kind              text not null check (kind in ('arr', 'dep')),
  op_time           timestamptz not null,
  op_time_source    text,            -- naive DataSF timestamp as published (SFO local)
  callsign          text,
  registration      text,
  aircraft_type     text,
  airline_icao      text,
  other_port        text,            -- origin for arr, destination for dep
  runway            text not null,
  museum_wof_id     bigint,
  trajectory_status text not null,
  match_method      text,
  source            text
);

create table if not exists public.track_points (
  operation_id text not null references public.flights (operation_id) on delete cascade,
  seq          int  not null,
  ts           timestamptz not null,
  lon          double precision not null,
  lat          double precision not null,
  altitude_raw text,                 -- FAA simpleAltitude string as published
  speed_raw    text,                 -- raw swim:speeds value
  alt_ft       int,                  -- parsed, null if unparseable
  spd_kt       int,
  primary key (operation_id, seq)
);

create table if not exists public.dataset_meta (
  key   text primary key,
  value jsonb not null
);

create index if not exists flights_op_time_idx on public.flights (op_time);
create index if not exists track_points_ts_idx on public.track_points (ts);

alter table public.flights      enable row level security;
alter table public.track_points enable row level security;
alter table public.dataset_meta enable row level security;

drop policy if exists "public read flights" on public.flights;
create policy "public read flights" on public.flights
  for select to anon, authenticated using (true);

drop policy if exists "public read track_points" on public.track_points;
create policy "public read track_points" on public.track_points
  for select to anon, authenticated using (true);

drop policy if exists "public read dataset_meta" on public.dataset_meta;
create policy "public read dataset_meta" on public.dataset_meta
  for select to anon, authenticated using (true);
-- No insert/update/delete policies: anon and authenticated cannot write.
