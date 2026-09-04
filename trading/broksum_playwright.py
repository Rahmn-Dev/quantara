"""
BrokSum Playwright Scraper
==========================
Scrapes broker summary (Ringkasan Broker) dari IDX menggunakan Playwright
dengan strategi network interception — browser real visit halaman IDX,
kita capture response API yang dipanggil oleh halaman tersebut.

Tidak hit IDX API langsung (yang di-block), tapi intercept saat
browser genuine melakukan request.

Requirements:
    pip install playwright
    playwright install chromium

Usage:
    from trading.broksum_playwright import fetch_broker_summary_playwright
    data = fetch_broker_summary_playwright("BBCA", "20260903")
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, timedelta
from typing import Any

log = logging.getLogger("quantara.broksum_playwright")

# --------------------------------------------------------------------------
# URL yang di-intercept saat browser visit halaman broksum IDX
# --------------------------------------------------------------------------
IDX_BROKSUM_PAGE = "https://www.idx.co.id/id/data-pasar/ringkasan-transaksi/ringkasan-broker/"
INTERCEPT_PATTERN = re.compile(r"BrokerSummary", re.IGNORECASE)


async def _fetch_broksum_async(symbol: str, trading_date: str, timeout_ms: int = 30000) -> dict | None:
    """
    Core async function: buka browser Chromium, visit halaman broksum IDX,
    intercept network response yang berisi data broker summary.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
        return None

    captured_data: dict | None = None

    async with async_playwright() as pw:
        # Pakai chromium headless (tidak kelihatan)
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="id-ID",
            timezone_id="Asia/Jakarta",
        )
        page = await context.new_page()

        # Intercept responses: kita capture response yang berisi BrokerSummary data
        async def handle_response(response):
            nonlocal captured_data
            if captured_data:
                return
            if INTERCEPT_PATTERN.search(response.url):
                try:
                    body = await response.json()
                    log.info("Captured BrokerSummary response from: %s", response.url)
                    captured_data = body
                except Exception as exc:
                    log.debug("Could not parse response from %s: %s", response.url, exc)

        page.on("response", handle_response)

        try:
            # 1. Visit halaman broksum IDX — ini akan trigger request ke API IDX
            log.info("Opening IDX BrokSum page for %s on %s...", symbol, trading_date)
            await page.goto(IDX_BROKSUM_PAGE, wait_until="domcontentloaded", timeout=timeout_ms)

            # 2. Cari input/select untuk kode saham dan tanggal, lalu fill
            # IDX halaman biasanya punya form input untuk saham
            await page.wait_for_timeout(2000)  # wait for JS to init

            # Coba fill input saham (selector bervariasi, coba beberapa)
            stock_selectors = [
                "input[placeholder*='Kode']",
                "input[placeholder*='saham']",
                "input[placeholder*='Stock']",
                "input[placeholder*='Symbol']",
                ".stock-code-input input",
                "#idxCode",
                "input[name='idxCode']",
            ]
            for sel in stock_selectors:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.fill(symbol)
                        log.debug("Filled stock code into: %s", sel)
                        break
                except Exception:
                    continue

            # Coba fill tanggal
            date_obj = date(
                int(trading_date[:4]),
                int(trading_date[4:6]),
                int(trading_date[6:8]),
            )
            date_formatted = date_obj.strftime("%d/%m/%Y")  # IDX biasanya dd/mm/yyyy

            date_selectors = [
                "input[placeholder*='Tanggal']",
                "input[placeholder*='Date']",
                "input[type='date']",
                ".date-picker input",
                "#tradingDate",
            ]
            for sel in date_selectors:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.fill(date_formatted)
                        log.debug("Filled date into: %s", sel)
                        break
                except Exception:
                    continue

            # Cari dan klik tombol cari/tampilkan
            search_selectors = [
                "button:has-text('Cari')",
                "button:has-text('Tampilkan')",
                "button:has-text('Show')",
                "button:has-text('Search')",
                "button[type='submit']",
                ".btn-search",
            ]
            for sel in search_selectors:
                try:
                    btn = page.locator(sel).first
                    if await btn.count() > 0:
                        await btn.click()
                        log.debug("Clicked search button: %s", sel)
                        break
                except Exception:
                    continue

            # Wait for network response to be captured (max 15s)
            for _ in range(30):
                if captured_data:
                    break
                await page.wait_for_timeout(500)

            if not captured_data:
                # Fallback: try direct URL approach with session cookies
                log.info("Form interaction failed, trying direct API call with browser cookies...")
                captured_data = await _try_direct_with_cookies(page, symbol, trading_date)

        except Exception as exc:
            log.warning("Playwright navigation error: %s", exc)
        finally:
            await browser.close()

    return captured_data


async def _try_direct_with_cookies(page, symbol: str, trading_date: str) -> dict | None:
    """
    Fallback: setelah browser punya session cookies dari visit halaman IDX,
    coba hit API endpoint langsung via page.evaluate (XMLHttpRequest dari konteks browser).
    """
    try:
        result = await page.evaluate(
            """
            async ([symbol, date]) => {
                const url = `https://www.idx.co.id/primary/BrokerSummary/GetBrokerSummary?idxCode=${symbol}&tradingDate=${date}`;
                const resp = await fetch(url, {
                    method: 'GET',
                    headers: {
                        'accept': 'application/json, text/plain, */*',
                        'referer': 'https://www.idx.co.id/id/data-pasar/ringkasan-transaksi/ringkasan-broker/',
                    },
                    credentials: 'include'
                });
                if (!resp.ok) return null;
                return await resp.json();
            }
            """,
            [symbol, trading_date],
        )
        if result:
            log.info("Direct cookie-based fetch succeeded for %s", symbol)
        return result
    except Exception as exc:
        log.warning("Direct cookie fetch failed: %s", exc)
        return None


def fetch_broker_summary_playwright(
    symbol: str,
    trading_date: str | None = None,
    fallback_days: int = 5,
) -> dict | None:
    """
    Public synchronous API: fetch broker summary for a given symbol and date.

    Args:
        symbol: Stock code, e.g. "BBCA"
        trading_date: YYYYMMDD string. Defaults to most recent trading day.
        fallback_days: How many previous days to try if today has no data.

    Returns:
        Raw API dict from IDX, or None if unavailable.
    """
    if trading_date is None:
        trading_date = date.today().strftime("%Y%m%d")

    # Try trading_date and fallback to previous days
    for days_back in range(fallback_days):
        target = date(
            int(trading_date[:4]),
            int(trading_date[4:6]),
            int(trading_date[6:8]),
        ) - timedelta(days=days_back)
        target_str = target.strftime("%Y%m%d")

        if target.weekday() >= 5:  # Skip weekends
            continue

        log.info("Trying Playwright broksum for %s on %s...", symbol, target_str)
        result = asyncio.run(_fetch_broksum_async(symbol, target_str))
        if result:
            return result

    log.warning("No broker summary data found for %s in last %d trading days", symbol, fallback_days)
    return None


# --------------------------------------------------------------------------
# Parse raw IDX BrokerSummary response into our BrokerFlow format
# --------------------------------------------------------------------------

def parse_broker_summary(raw: dict, symbol: str, trading_date: str) -> dict:
    """
    Parse raw IDX BrokerSummary API response into the same format
    as BrokerFlowAdapter.compute_flow_score().

    Returns a dict compatible with BrokerFlow model.
    """
    result = {
        "symbol": symbol,
        "date": trading_date,
        "cr1": None, "cr3": None, "cr5": None,
        "net_foreign_value": None,
        "institutional_score": 50.0,
        "top_brokers": [],
        "raw_available": False,
        "source": "playwright_idx",
    }

    if not raw:
        return result

    try:
        # IDX BrokerSummary response structure:
        # { "BrokerBuy": [{BrokerCode, TotalVolume, TotalValue, Frequency, ...}],
        #   "BrokerSell": [{...}] }
        buy_items = raw.get("BrokerBuy", []) or []
        sell_items = raw.get("BrokerSell", []) or []

        buy_map: dict[str, float] = {}
        sell_map: dict[str, float] = {}

        for entry in buy_items:
            code = str(entry.get("BrokerCode") or entry.get("BCode") or "")
            val = float(entry.get("TotalValue") or entry.get("Value") or 0)
            buy_map[code] = buy_map.get(code, 0) + val

        for entry in sell_items:
            code = str(entry.get("BrokerCode") or entry.get("BCode") or "")
            val = float(entry.get("TotalValue") or entry.get("Value") or 0)
            sell_map[code] = sell_map.get(code, 0) + val

        all_brokers = set(buy_map) | set(sell_map)
        if not all_brokers:
            return result

        net_map = {b: buy_map.get(b, 0) - sell_map.get(b, 0) for b in all_brokers}
        total_buy = sum(buy_map.values()) or 1
        total_activity = sum(buy_map.get(b, 0) + sell_map.get(b, 0) for b in all_brokers) or 1

        sorted_buy = sorted(buy_map.values(), reverse=True)
        cr1 = round(sorted_buy[0] / total_buy * 100, 2) if sorted_buy else 0
        cr3 = round(sum(sorted_buy[:3]) / total_buy * 100, 2) if len(sorted_buy) >= 3 else cr1
        cr5 = round(sum(sorted_buy[:5]) / total_buy * 100, 2) if len(sorted_buy) >= 5 else cr3

        sorted_brokers = sorted(
            all_brokers,
            key=lambda b: buy_map.get(b, 0) + sell_map.get(b, 0),
            reverse=True,
        )
        top_brokers = [
            {
                "code": b,
                "buy": round(buy_map.get(b, 0), 0),
                "sell": round(sell_map.get(b, 0), 0),
                "net": round(net_map.get(b, 0), 0),
                "share_pct": round((buy_map.get(b, 0) + sell_map.get(b, 0)) / total_activity * 100, 2),
            }
            for b in sorted_brokers[:10]
        ]

        # Institutional score: CR3 proxy for bandar concentration
        institutional_score = min(95, max(20, 20 + cr3 * 1.5 + cr1 * 0.5))

        result.update({
            "cr1": cr1, "cr3": cr3, "cr5": cr5,
            "institutional_score": round(institutional_score, 2),
            "top_brokers": top_brokers,
            "raw_available": True,
            "source": "playwright_idx",
        })

    except Exception as exc:
        log.warning("parse_broker_summary error for %s: %s", symbol, exc)

    return result


# --------------------------------------------------------------------------
# Convenience: scrape + parse in one call
# --------------------------------------------------------------------------

def scrape_and_parse_broksum(symbol: str, trading_date: str | None = None) -> dict:
    """Scrape broker summary via Playwright and return parsed dict."""
    if trading_date is None:
        trading_date = date.today().strftime("%Y%m%d")
    raw = fetch_broker_summary_playwright(symbol, trading_date)
    return parse_broker_summary(raw, symbol, trading_date)
