# Karo UK Price Scanner

Daily price monitoring of E45 products on Boots UK (boots.com).

Prices are scraped every night at 03:00 UTC and stored in Supabase. The scraper uses plain HTTP requests where possible, with Playwright as a fallback for JavaScript-rendered pages.

## Setup

**1. Supabase**

Create a new Supabase project. Run `supabase_schema.sql` in the SQL editor to create the `produkter` and `prices` tables, convenience views, and RLS policies.

**2. GitHub Secrets**

Add the following secrets to the repository (Settings → Secrets → Actions):

| Secret | Value |
|---|---|
| `SUPABASE_URL` | Your project URL, e.g. `https://xyz.supabase.co` |
| `SUPABASE_SERVICE_KEY` | Service role key (bypasses RLS for writes) |

**3. Seed products**

Trigger the workflow manually from the Actions tab, or run locally:

```bash
cd scraper
pip install -r requirements.txt
python scripts/seed_products.py
```

This upserts all products from `scripts/products.csv` into the database.

## Managing products

All products are defined in `scraper/scripts/products.csv`:

```
product_id,brand,product,category,url
10093007,E45,E45 Cream 350g,Emollient,https://www.boots.com/e45-cream-...
```

To add or remove products, edit the CSV and re-run `seed_products.py`. To stop tracking a product without losing its price history, set `active = false` directly in Supabase.

## How it works

The GitHub Actions workflow (`.github/workflows/daily.yml`) runs every night at 03:00 UTC. It seeds products, then runs the scraper.

Each product is scraped in two passes:
1. **HTTP request** — fast, no browser needed. Works if the price is embedded in meta tags or structured data.
2. **Playwright fallback** — for products where Boots renders the price via JavaScript.

All prices are inserted into the `prices` table with a GBP currency marker and stock status.

## Project structure

```
.
├── .github/workflows/daily.yml   # Scheduled GitHub Actions job
├── scraper/
│   ├── run.py                    # Main entry point
│   ├── db.py                     # Supabase client and helpers
│   ├── requirements.txt
│   ├── .env.example
│   ├── scrapers/
│   │   └── boots_uk.py           # Boots UK scraper (HTTP + Playwright)
│   └── scripts/
│       ├── products.csv          # Product catalogue
│       └── seed_products.py      # Upserts CSV into Supabase
├── supabase_schema.sql           # Full DB schema
└── .gitignore
```

## Local development

```bash
cd scraper
cp .env.example .env              # add your Supabase credentials
pip install -r requirements.txt
playwright install chromium
python run.py                     # full run
python run.py --dry-run           # scrape without writing to DB
```

## Adding more retailers

The architecture supports adding more UK retailers (e.g. Superdrug, Tesco, Amazon UK). Create a new scraper module in `scraper/scrapers/`, add a `retailer` column value, and call it from `run.py`.
