-- ============================================================
-- Karo UK Price Scanner — Supabase Schema
-- ============================================================

-- Products table
create table produkter (
  id           bigint generated always as identity primary key,
  product_id   text not null unique,           -- Boots product ID (e.g. "10093007")
  brand        text not null default 'E45',
  product      text not null,                  -- Full product name
  category     text not null default 'Skincare',
  type         text not null default 'own',     -- 'own' or 'competitor'
  url          text,                           -- Cached boots.com URL
  active       boolean not null default true,
  created_at   timestamptz default now()
);

-- Price history table
create table prices (
  id           bigint generated always as identity primary key,
  product_id   text not null references produkter(product_id),
  retailer     text not null default 'Boots UK',
  price        numeric(8,2) not null,
  currency     text not null default 'GBP',
  in_stock     boolean default true,
  scraped_at   timestamptz default now()
);

-- Index for fast lookups
create index idx_prices_product_date on prices (product_id, scraped_at desc);
create index idx_prices_scraped_at on prices (scraped_at desc);
create index idx_produkter_active on produkter (active) where active = true;

-- ============================================================
-- Views
-- ============================================================

-- Latest price per product
create or replace view latest_prices as
select distinct on (p.product_id)
  p.product_id,
  p.brand,
  p.product,
  p.category,
  p.type,
  pr.price,
  pr.currency,
  pr.in_stock,
  pr.scraped_at,
  p.url
from produkter p
join prices pr on pr.product_id = p.product_id
where p.active = true
order by p.product_id, pr.scraped_at desc;

-- Price comparison over time (last 90 days)
create or replace view price_history as
select
  p.product_id,
  p.brand,
  p.product,
  p.category,
  p.type,
  pr.price,
  pr.currency,
  pr.in_stock,
  pr.scraped_at::date as date,
  pr.scraped_at
from produkter p
join prices pr on pr.product_id = p.product_id
where pr.scraped_at > now() - interval '90 days'
order by p.product_id, pr.scraped_at desc;

-- ============================================================
-- RLS policies
-- ============================================================

alter table produkter enable row level security;
alter table prices enable row level security;

-- Public read access
create policy "Public read produkter" on produkter for select using (true);
create policy "Public read prices" on prices for select using (true);

-- Service key write access
create policy "Service insert produkter" on produkter for insert with check (true);
create policy "Service update produkter" on produkter for update using (true);
create policy "Service insert prices" on prices for insert with check (true);
