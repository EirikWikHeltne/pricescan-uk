"""
Boots UK (boots.com) scraper.

Uses the IBM WebSphere Commerce REST API directly — no browser needed.
Endpoint: /search/resources/store/11352/productview/byPartNumber/{partNumber}
"""

import re
from datetime import datetime, timezone

import httpx

API_BASE = "https://www.boots.com/search/resources/store/11352/productview/byPartNumber"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-GB,en;q=0.9",
}


def _extract_part_number(url: str) -> str | None:
    if not url:
        return None
    m = re.search(r'(\d{7,8})', url)
    return m.group(1) if m else None


def _fetch_product(client: httpx.Client, part_number: str) -> dict | None:
    try:
        r = client.get(f"{API_BASE}/{part_number}")
        if r.status_code != 200:
            return None
        data = r.json()
        entries = data.get("catalogEntryView", [])
        return entries[0] if entries else None
    except Exception:
        return None


def _extract_price(entry: dict) -> tuple[float | None, float | None, bool]:
    prices = entry.get("price", [])
    offer_price = None
    display_price = None

    for p in prices:
        val = p.get("value", "")
        if not val:
            continue
        try:
            amount = float(val)
        except (ValueError, TypeError):
            continue
        usage = p.get("usage", "")
        if usage == "Offer":
            offer_price = amount
        elif usage == "Display" and amount > 0:
            display_price = amount

    was_price = None
    if display_price and offer_price and display_price > offer_price:
        was_price = display_price

    buyable = entry.get("buyable", "true") == "true"
    return offer_price, was_price, buyable


async def scrape_all(products: list[dict]) -> list[dict]:
    results = []
    now = datetime.now(timezone.utc).isoformat()

    with httpx.Client(follow_redirects=True, timeout=15, headers=HEADERS) as client:
        for p in products:
            url = p.get("url", "")
            part_number = _extract_part_number(url)

            if not part_number:
                print(f"  ⚠ {p['product']}: no part number in URL")
                continue

            entry = _fetch_product(client, part_number)
            if not entry:
                print(f"  ⚠ {p['product']}: API returned no data (PN: {part_number})")
                continue

            price, was_price, in_stock = _extract_price(entry)
            if price is None:
                print(f"  ⚠ {p['product']}: no price in API response")
                continue

            results.append({
                "product_id": p["product_id"],
                "retailer": "Boots UK",
                "price": price,
                "currency": "GBP",
                "in_stock": in_stock,
                "scraped_at": now,
            })

            promo = f" (was £{was_price:.2f}, -{round((1-price/was_price)*100)}%)" if was_price else ""
            stock = " ✓" if in_stock else " [OOS]"
            print(f"  ✓ {p['product']}: £{price:.2f}{promo}{stock}")

    return results
