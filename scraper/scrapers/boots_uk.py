"""
Boots UK (boots.com) scraper.

Strategy:
1. Try HTTP request first (faster, less resource-intensive)
2. Fall back to Playwright for JS-rendered pages
3. Extract price from meta tags, JSON-LD, or DOM selectors
"""

import json
import re
from datetime import datetime, timezone

import httpx
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


# ── Price extraction helpers ──────────────────────────────────────────────────

def _extract_price_from_html(html: str) -> tuple[float | None, bool]:
    """
    Try to extract price from raw HTML without full JS rendering.
    Boots pages sometimes embed price in meta tags or structured data.
    """
    price = None
    in_stock = True

    # Try og:price / product:price meta tags
    m = re.search(r'<meta\s+(?:property|name)="(?:og:price:amount|product:price:amount)"\s+content="([\d.]+)"', html)
    if m:
        price = float(m.group(1))

    # Try JSON-LD structured data
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL):
        try:
            data = json.loads(m.group(1))
            if isinstance(data, dict):
                offers = data.get("offers", {})
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                if "price" in offers:
                    price = float(offers["price"])
                if offers.get("availability", "").lower().endswith("outofstock"):
                    in_stock = False
        except (json.JSONDecodeError, ValueError, IndexError):
            continue

    # Try embedded product JSON (Boots WCS pattern)
    m = re.search(r'"productPrice"\s*:\s*"£?([\d.]+)"', html)
    if m and price is None:
        price = float(m.group(1))

    # Check stock
    if "temporarily unavailable" in html.lower() or "out of stock" in html.lower():
        in_stock = False

    return price, in_stock


def _extract_price_from_page_text(text: str) -> tuple[float | None, bool]:
    """Extract price from rendered page text content."""
    price = None
    in_stock = True

    # Look for £X.XX pattern
    prices = re.findall(r'£([\d]+\.[\d]{2})', text)
    if prices:
        # First price match is usually the current/sale price
        price = float(prices[0])

    if "temporarily unavailable" in text.lower() or "out of stock" in text.lower():
        in_stock = False

    return price, in_stock


# ── Main scraper ─────────────────────────────────────────────────────────────

async def scrape_product_http(url: str) -> tuple[float | None, bool]:
    """Try scraping with plain HTTP request first (fast path)."""
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-GB,en;q=0.9",
            },
        ) as client:
            r = await client.get(url)
            if r.status_code == 200:
                return _extract_price_from_html(r.text)
    except Exception:
        pass
    return None, True


async def scrape_product_playwright(url: str, page) -> tuple[float | None, bool]:
    """
    Scrape a single Boots UK product page using Playwright.
    Expects an already-created page object.
    """
    price = None
    in_stock = True

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Wait for price to render — Boots uses multiple possible selectors
        price_selectors = [
            '[data-testid="product-price"]',
            '.product_price .Price_current',
            '.product_price .price',
            '.price_price',
            '#widget_product_price .price',
            '.pdp_price',
            'span.Price_current_price',
        ]

        for selector in price_selectors:
            try:
                el = await page.wait_for_selector(selector, timeout=5000)
                if el:
                    text = await el.inner_text()
                    m = re.search(r'£([\d]+\.[\d]{2})', text)
                    if m:
                        price = float(m.group(1))
                        break
            except PlaywrightTimeoutError:
                continue

        # If no selector worked, try extracting from full page text
        if price is None:
            text = await page.inner_text("body")
            price, in_stock = _extract_price_from_page_text(text)
        else:
            # Check stock status
            content = await page.content()
            if "temporarily unavailable" in content.lower() or "out of stock" in content.lower():
                in_stock = False

    except PlaywrightTimeoutError:
        print(f"  ⏱  Timeout: {url}")
    except Exception as e:
        print(f"  ❌ Error scraping {url}: {e}")

    return price, in_stock


async def scrape_all(products: list[dict]) -> list[dict]:
    """
    Scrape prices for all products.
    Tries HTTP first, falls back to Playwright.
    """
    results = []
    now = datetime.now(timezone.utc).isoformat()

    # First pass: try HTTP for all products
    http_done = set()
    for p in products:
        url = p.get("url")
        if not url:
            continue

        price, in_stock = await scrape_product_http(url)
        if price is not None:
            results.append({
                "product_id": p["product_id"],
                "retailer": "Boots UK",
                "price": price,
                "currency": "GBP",
                "in_stock": in_stock,
                "scraped_at": now,
            })
            http_done.add(p["product_id"])
            print(f"  ✓ {p['product']}: £{price:.2f} {'(in stock)' if in_stock else '(OOS)'} [HTTP]")

    # Second pass: Playwright for remaining products
    remaining = [p for p in products if p["product_id"] not in http_done and p.get("url")]
    if remaining:
        print(f"\n  🎭 Launching Playwright for {len(remaining)} remaining products...")
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                locale="en-GB",
                viewport={"width": 1280, "height": 720},
            )

            # Accept cookies once
            page = await context.new_page()
            try:
                await page.goto("https://www.boots.com", wait_until="domcontentloaded", timeout=20000)
                cookie_btn = await page.query_selector('[id*="onetrust-accept"], [class*="cookie-accept"], button:has-text("Accept")')
                if cookie_btn:
                    await cookie_btn.click()
                    await page.wait_for_timeout(1000)
            except Exception:
                pass

            for p in remaining:
                url = p["url"]
                price, in_stock = await scrape_product_playwright(url, page)

                if price is not None:
                    results.append({
                        "product_id": p["product_id"],
                        "retailer": "Boots UK",
                        "price": price,
                        "currency": "GBP",
                        "in_stock": in_stock,
                        "scraped_at": now,
                    })
                    print(f"  ✓ {p['product']}: £{price:.2f} {'(in stock)' if in_stock else '(OOS)'} [Playwright]")
                else:
                    print(f"  ⚠ {p['product']}: no price found")

            await browser.close()

    return results
