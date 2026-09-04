"""
Phase 2 — Financial Fundamentals Sync

Fetches PER, PBV, ROE, DER, EPS for all IDX-listed stocks and stores
them in FundamentalSnapshot. Designed to run as a weekly Celery task.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from .idx_bei_adapter import FinancialRatioAdapter
from .models import FundamentalSnapshot, Instrument

log = logging.getLogger("quantara.fundamental_sync")


def sync_fundamentals(year: int | None = None, quarter: int = 4) -> dict:
    """
    Fetch financial ratios from IDX and upsert into FundamentalSnapshot.

    Returns a summary dict: {synced, skipped, errors}.
    """
    adapter = FinancialRatioAdapter()
    current_year = year or timezone.localdate().year

    log.info("Fetching financial ratios for FY%dQ%d...", current_year, quarter)
    rows = adapter.fetch_all_ratios(year=current_year, quarter=quarter)

    if not rows:
        # Fallback: try previous year
        fallback_year = current_year - 1
        log.warning("No ratios for FY%d, trying FY%d...", current_year, fallback_year)
        rows = adapter.fetch_all_ratios(year=fallback_year, quarter=quarter)
        if rows:
            current_year = fallback_year

    synced, skipped, errors = 0, 0, []

    for row in rows:
        parsed = adapter.parse_ratio(row)
        symbol = parsed.get("symbol", "").strip()
        if not symbol or len(symbol) < 2:
            skipped += 1
            continue

        try:
            instrument = Instrument.objects.filter(symbol=symbol, is_active=True).first()
            if not instrument:
                skipped += 1
                continue

            FundamentalSnapshot.objects.update_or_create(
                instrument=instrument,
                period_year=current_year,
                period_quarter=quarter,
                defaults={
                    "per": parsed.get("per"),
                    "pbv": parsed.get("pbv"),
                    "roe": parsed.get("roe"),
                    "der": parsed.get("der"),
                    "eps": parsed.get("eps"),
                    "revenue_growth": parsed.get("revenue_growth"),
                },
            )
            synced += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{symbol}: {exc}")

    log.info("Fundamentals synced: %d ok, %d skipped, %d errors", synced, skipped, len(errors))
    return {"synced": synced, "skipped": skipped, "errors": errors, "year": current_year, "quarter": quarter}
