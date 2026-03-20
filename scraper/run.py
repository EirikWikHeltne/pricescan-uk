"""
Karo UK Price Scanner — Main entry point.

Usage:
  python run.py           # Scrape all active products
  python run.py --dry-run # Scrape but don't write to Supabase
"""

import asyncio
import sys
from datetime import datetime, timezone

from db import get_active_products, insert_prices
from scrapers.boots_uk import scrape_all


async def main():
    dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print(f"  Karo UK Price Scanner")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # 1. Load active products
    products = get_active_products()
    print(f"\n📦 {len(products)} active products loaded from Supabase\n")

    if not products:
        print("⚠️  No active products found. Run seed_products.py first.")
        return

    # 2. Scrape Boots UK
    print("🏪 Scraping Boots UK (boots.com)...")
    results = await scrape_all(products)

    # 3. Write to Supabase
    if results and not dry_run:
        insert_prices(results)
        print(f"\n✅ Inserted {len(results)} price records into Supabase")
    elif dry_run:
        print(f"\n🧪 Dry run — {len(results)} records would have been inserted")
    else:
        print("\n⚠️  No prices collected")

    # 4. Summary
    missing = set(p["product_id"] for p in products) - set(r["product_id"] for r in results)
    if missing:
        missing_names = [p["product"] for p in products if p["product_id"] in missing]
        print(f"\n⚠️  Missing prices for: {', '.join(sorted(missing_names))}")

    print(f"\n{'=' * 60}")
    print(f"  Done. {len(results)}/{len(products)} products scraped.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
