-- early_access_waitlist — captures signups from fisga.co/early-access
-- Run once in the Supabase project (fcvbchxnbikqcatsfpeh) SQL Editor.
-- The page inserts client-side with the public anon key (same pattern as website_leads),
-- so RLS must allow the `anon` role to INSERT (but not read).

create table if not exists public.early_access_waitlist (
  id         uuid primary key default gen_random_uuid(),
  name       text,
  company    text,
  email      text not null unique,
  role       text,
  source     text default 'early-access-page',
  created_at timestamptz not null default now()
);

-- If the table already exists, add the new columns:
alter table public.early_access_waitlist add column if not exists name    text;
alter table public.early_access_waitlist add column if not exists company text;

alter table public.early_access_waitlist enable row level security;

-- Allow anonymous inserts from the marketing site (no read/update/delete for anon).
drop policy if exists "anon can join waitlist" on public.early_access_waitlist;
create policy "anon can join waitlist"
  on public.early_access_waitlist
  for insert
  to anon
  with check (true);
