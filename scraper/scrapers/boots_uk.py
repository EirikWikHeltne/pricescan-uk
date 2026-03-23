"""
Supabase client and query helpers for Karo UK Price Scanner.
"""

import os
from functools import lru_cache

import httpx

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=f"{SUPABASE_URL}/rest/v1",
        headers=HEADERS,
        timeout=30,
    )


def get_active_products() -> list[dict]:
    """Return all active products from the produkter table."""
    with _client() as c:
        r = c.get("/produkter", params={"active": "eq.true", "select": "*"})
        r.raise_for_status()
        return r.json()


def upsert_products(rows: list[dict]) -> None:
    """Upsert products into the produkter table."""
    with _client() as c:
        r = c.post(
            "/produkter",
            json=rows,
            headers={
                **HEADERS,
                "Prefer": "resolution=merge-duplicates",
                "Content-Type": "application/json",
            },
            params={"on_conflict": "product_id"},
        )
        r.raise_for_status()


def insert_prices(rows: list[dict]) -> None:
    """Bulk insert price records."""
    if not rows:
        return
    with _client() as c:
        r = c.post("/prices", json=rows)
        r.raise_for_status()


def update_product_url(product_id: str, url: str) -> None:
    """Cache a resolved product URL back to the produkter table."""
    with _client() as c:
        r = c.patch(
            "/produkter",
            params={"product_id": f"eq.{product_id}"},
            json={"url": url},
        )
        r.raise_for_status()
