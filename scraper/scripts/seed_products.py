"""
Seed products from CSV into Supabase.
Run once after setup, or anytime the product list changes:
  python scripts/seed_products.py
"""

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import upsert_products

CSV_PATH = os.path.join(os.path.dirname(__file__), "products.csv")


def seed():
    with open(CSV_PATH, encoding="utf-8") as f:
        rows = [
            {
                "product_id": r["product_id"].strip(),
                "brand": r["brand"].strip(),
                "product": r["product"].strip(),
                "category": r["category"].strip(),
                "type": r.get("type", "own").strip(),
                "url": r["url"].strip() or None,
            }
            for r in csv.DictReader(f)
            if r.get("product_id", "").strip()
        ]

    upsert_products(rows)
    print(f"✅ Seeded {len(rows)} products from {CSV_PATH}")


if __name__ == "__main__":
    seed()
