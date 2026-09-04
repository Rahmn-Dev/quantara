"""
Phase 1 — Broker Flow / Bandarmologi Sync

Primary scraper: Playwright (real Chromium browser) → bypass IDX anti-bot
Fallback: curl_cffi direct API (works if IDX API is accessible without block)

Playwright strategy:
  1. Visit IDX ringkasan broker page (real browser session)
  2. Intercept network response OR use browser cookies for direct API call
  3. Parse CR1/CR3/CR5 and institutional score
"""

from __future__ import annotations

import logging
import time

from django.utils import timezone

from .models import BrokerFlow, Instrument
from .stockbit_adapter import StockbitAdapter

log = logging.getLogger("quantara.broker_flow_sync")



def sync_broker_flows(
    trading_date: str | None = None,
    instruments: list | None = None,
    delay_seconds: float = 2.0,
) -> dict:
    """
    Sync broker flow data for all active instruments.

    Primary:  Playwright (real browser, bypasses IDX anti-bot) 
    Fallback: curl_cffi direct API (fast but may be blocked)

    Args:
        trading_date: Date string YYYYMMDD. Defaults to today.
        instruments: Queryset/list of Instrument. Defaults to all active.
        delay_seconds: Delay between API calls (Stockbit is lighter, but 2s is safe).

    Returns:
        Summary dict: {synced, skipped, errors, date, source}.
    """
    adapter = StockbitAdapter()
    date_str = trading_date or timezone.localdate().strftime("%Y%m%d")
    target_date = timezone.localdate()

    if instruments is None:
        instruments = Instrument.objects.filter(is_active=True)

    synced, skipped, errors = 0, 0, []
    stockbit_ok_count = 0

    for instrument in instruments:
        try:
            flow_data = None

            log.debug("Stockbit: fetching broksum for %s...", instrument.symbol)
            raw_data = adapter.fetch_broker_summary(instrument.symbol)
            flow_data = adapter.parse_flow_score(instrument.symbol, raw_data)
            
            if flow_data and flow_data.get("raw_available"):
                stockbit_ok_count += 1
                log.info(
                    "%s [Stockbit] CR1=%.1f%% CR3=%.1f%% Score=%.1f",
                    instrument.symbol,
                    flow_data.get("cr1") or 0,
                    flow_data.get("cr3") or 0,
                    flow_data.get("institutional_score", 50),
                )
            else:
                flow_data = None

            # --- Store to DB ---
            if flow_data:
                BrokerFlow.objects.update_or_create(
                    instrument=instrument,
                    trading_date=target_date,
                    defaults={
                        "cr1": flow_data.get("cr1"),
                        "cr3": flow_data.get("cr3"),
                        "cr5": flow_data.get("cr5"),
                        "institutional_score": flow_data.get("institutional_score", 50.0),
                        "net_foreign_value": flow_data.get("net_foreign_value"),
                        "top_brokers": flow_data.get("top_brokers", []),
                        "raw_available": bool(flow_data.get("raw_available")),
                    },
                )
                if flow_data.get("raw_available"):
                    synced += 1
                else:
                    skipped += 1
            else:
                skipped += 1

            time.sleep(delay_seconds)

        except Exception as exc:
            errors.append(f"{instrument.symbol}: {exc}")
            log.warning("Broker flow error for %s: %s", instrument.symbol, exc)

    log.info(
        "Broker flow sync done: %d synced (%d stockbit), %d skipped, %d errors",
        synced, stockbit_ok_count, skipped, len(errors),
    )
    return {
        "synced": synced,
        "skipped": skipped,
        "errors": errors,
        "date": date_str,
        "stockbit_ok": stockbit_ok_count,
    }

