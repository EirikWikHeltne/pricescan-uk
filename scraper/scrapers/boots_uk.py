"""
Boots UK (boots.com) scraper — v2

Boots runs IBM WebSphere Commerce with aggressive bot protection.
Strategy:
1. Use Playwright with stealth settings
2. Accept cookie consent first
3. Scrape brand listing pages (boots.com/e45) for bulk price extraction
4. Fall back to individual product pages for competitors
5. Extract price from rendered page text using regex patterns
"""

import json
import re
from datetime import datetime, timezone

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


# ── Price extraction from page text ──────────────────────────────────────────

def extract_prices_from_listing_text(text: str, products: list[dict]) -> dict:
    """
    Parse a listing page's full text to find product names and prices.
    Returns {product_id: (price, in_stock)}
    """
    results = {}

    for product in products:
        name = product["product"]
        parts = name.split()

        patterns = []
        # Try exact product name
        patterns.append(re.escape(name))
        # Try without brand (e.g. "Cream 350g", "Moisturising Lotion 500ml")
        if len(parts) > 1:
            patterns.append(re.escape(" ".join(parts[1:])))

        for pattern in patterns:
            m = re.search(
                pattern + r'.{0,300}?£(\d+\.?\d{0,2})',
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if m:
                try:
                    price = float(m.group(1))
                    if 0.5 < price < 200:
                        ctx = text[max(0, m.start() - 50) : m.end() + 200].lower()
                        in_stock = "temporarily unavailable" not in ctx
                        results[product["product_id"]] = (price, in_stock)
                        break
                except ValueError:
                    continue

    return results


def extract_price_from_product_text(text: str) -> tuple[float | None, bool]:
    """Extract price from a single product page's rendered text."""
    price = None
    in_stock = True

    all_prices = re.findall(r'£(\d+\.?\d{0,2})', text)
    valid = [float(p) for p in all_prices if 0.5 < float(p) < 200]

    if valid:
        price = valid[0]

    if "temporarily unavailable" in text.lower() or "out of stock" in text.lower():
        in_stock = False

    return price, in_stock


# ── Browser setup ────────────────────────────────────────────────────────────

async def create_stealth_context(playwright):
    """Browser context with stealth settings."""
    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1366, "height": 768},
        locale="en-GB",
        timezone_id="Europe/London",
    )
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-GB', 'en'] });
    """)
    return browser, context


async def accept_cookies(page):
    """Accept cookie consent banner."""
    for sel in [
        'button#onetrust-accept-btn-handler',
        'button[id*="accept"]',
        'button:has-text("Accept All")',
        'button:has-text("Accept all")',
        'button:has-text("Accept")',
    ]:
        try:
            btn = await page.wait_for_selector(sel, timeout=5000)
            if btn:
                await btn.click()
                await page.wait_for_timeout(2000)
                print("  🍪 Cookie consent accepted")
                return True
        except Exception:
            continue
    return False


# ── Listing page scraper ─────────────────────────────────────────────────────

async def scrape_listing_page(page, url: str, products: list[dict]) -> dict:
    """Scrape a brand listing page for bulk price extraction."""
    results = {}
    try:
        print(f"  📄 Loading listing: {url}")
        await page.goto(url, wait_until="networkidle", timeout=45000)
        await page.wait_for_timeout(4000)

        # Scroll to trigger lazy-loaded products
        for _ in range(5):
            await page.evaluate("window.scrollBy(0, 600)")
            await page.wait_for_timeout(800)
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(1000)

        text = await page.inner_text("body")
        results = extract_prices_from_listing_text(text, products)

        if not results:
            # Fallback: parse raw HTML for embedded WCS price data
            content = await page.content()
            for product in products:
                pid = product["product_id"]
                # Boots often embeds "PRODUCT_ID PRICE" in listing HTML
                m = re.search(rf'{pid}\s+(\d+\.\d{{2}})', content)
                if m:
                    try:
                        price = float(m.group(1))
                        if 0.5 < price < 200:
                            results[pid] = (price, True)
                    except ValueError:
                        pass

        print(f"  → {len(results)} prices from listing")
    except PlaywrightTimeoutError:
        print(f"  ⏱ Timeout on listing: {url}")
    except Exception as e:
        print(f"  ❌ Listing error: {e}")

    return results


# ── Individual product page scraper ──────────────────────────────────────────

async def scrape_product_page(page, product: dict) -> tuple[float | None, bool]:
    """Scrape a single product page."""
    url = product.get("url")
    if not url:
        return None, True

    try:
        await page.goto(url, wait_until="networkidle", timeout=40000)
        await page.wait_for_timeout(4000)

        text = await page.inner_text("body")
        price, in_stock = extract_price_from_product_text(text)

        if price is None:
            content = await page.content()
            # Try JSON-LD
            for blob in re.findall(
                r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
                content,
                re.DOTALL,
            ):
                try:
                    data = json.loads(blob)
                    offers = data.get("offers", {})
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    if "price" in offers:
                        price = float(offers["price"])
                        break
                except Exception:
                    continue

            # Try WCS price patterns in raw HTML
            if price is None:
                for pattern in [
                    r'"productPrice"\s*:\s*"£?([\d.]+)"',
                    r'"offerPrice"\s*:\s*"?(\d+\.?\d*)"?',
                    r'"price"\s*:\s*"?(\d+\.\d{2})"?',
                ]:
                    m = re.search(pattern, content)
                    if m:
                        try:
                            price = float(m.group(1))
                            if 0.5 < price < 200:
                                break
                            price = None
                        except ValueError:
                            continue

            if "temporarily unavailable" in content.lower():
                in_stock = False

        return price, in_stock

    except PlaywrightTimeoutError:
        print(f"  ⏱ Timeout: {product['product']}")
    except Exception as e:
        print(f"  ❌ Error: {product['product']}: {e}")
    return None, True


# ── Main orchestrator ────────────────────────────────────────────────────────

BRAND_LISTING_URLS = {
    "E45":    "https://www.boots.com/e45",
    "CeraVe": "https://www.boots.com/cerave",
    "Nivea":  "https://www.boots.com/nivea",
    "Aveeno": "https://www.boots.com/aveeno",
}


async def scrape_all(products: list[dict]) -> list[dict]:
    """
    Two-pass strategy:
    1. Brand listing pages for bulk extraction
    2. Individual product pages for anything missed
    """
    results = []
    found = set()
    now = datetime.now(timezone.utc).isoformat()

    async with async_playwright() as pw:
        browser, context = await create_stealth_context(pw)
        page = await context.new_page()

        # Accept cookies on homepage first
        try:
            await page.goto(
                "https://www.boots.com",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await page.wait_for_timeout(3000)
            await accept_cookies(page)
        except Exception as e:
            print(f"  ⚠ Homepage: {e}")

        # Pass 1 — brand listing pages
        print("\n  📋 Pass 1: Brand listing pages...")
        brands_in_data = set(p["brand"] for p in products)

        for brand, url in BRAND_LISTING_URLS.items():
            if brand not in brands_in_data:
                continue
            brand_products = [p for p in products if p["brand"] == brand]
            listing_results = await scrape_listing_page(page, url, brand_products)

            for pid, (price, in_stock) in listing_results.items():
                prod = next((p for p in products if p["product_id"] == pid), None)
                if prod:
                    results.append({
                        "product_id": pid,
                        "retailer": "Boots UK",
                        "price": price,
                        "currency": "GBP",
                        "in_stock": in_stock,
                        "scraped_at": now,
                    })
                    found.add(pid)
                    print(f"    ✓ {prod['product']}: £{price:.2f} [listing]")

        # Pass 2 — individual product pages
        remaining = [p for p in products if p["product_id"] not in found and p.get("url")]
        if remaining:
            print(f"\n  🔍 Pass 2: {len(remaining)} individual pages...")
            for product in remaining:
                price, in_stock = await scrape_product_page(page, product)
                if price is not None:
                    results.append({
                        "product_id": product["product_id"],
                        "retailer": "Boots UK",
                        "price": price,
                        "currency": "GBP",
                        "in_stock": in_stock,
                        "scraped_at": now,
                    })
                    found.add(product["product_id"])
                    print(f"    ✓ {product['product']}: £{price:.2f} [individual]")
                else:
                    print(f"    ⚠ {product['product']}: no price found")

        await browser.close()

    return results
