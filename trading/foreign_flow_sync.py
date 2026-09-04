"""
Phase 3 — Foreign Flow Radar Sync

Fetches daily net foreign buy/sell from IDX StockSummary API and stores
ForeignFlow records. Computes a 5-day rolling signal: ACCUMULATE / DISTRIBUTE / NEUTRAL.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from .idx_bei_adapter import ForeignFlowAdapter
from .models import ForeignFlow, Instrument

log = logging.getLogger("quantara.foreign_flow_sync")


def _safe_float(val, default=0.0) -> float:
    try:
        return float(val) if val not in (None, "", "-") else default
    except (TypeError, ValueError):
        return default


def sync_foreign_flows(trading_date: str | None = None) -> dict:
    """
    Fetch the stock summary for a given date and upsert ForeignFlow records.
    Also recomputes the rolling 5-day signal for each instrument.

    Returns summary: {synced, skipped, errors}.
    """
    adapter = ForeignFlowAdapter()
    date_str = trading_date or timezone.localdate().strftime("%Y%m%d")
    target_date = timezone.localdate()

    log.info("Fetching stock summary (foreign flows) for %s...", date_str)
    rows = adapter.fetch_stock_summary(trading_date=date_str)

    if not rows:
        log.warning("No stock summary data returned for %s", date_str)
        return {"synced": 0, "skipped": 0, "errors": ["IDX StockSummary returned no data"], "date": date_str}

    # Build symbol map for quick lookup
    row_map: dict[str, dict] = {}
    for row in rows:
        sym = (row.get("StockCode") or row.get("IDxCode") or "").strip().upper()
        if sym:
            row_map[sym] = row

    synced, skipped, errors = 0, 0, []

    for instrument in Instrument.objects.filter(is_active=True):
        row = row_map.get(instrument.symbol)
        if not row:
            skipped += 1
            continue

        try:
            # Field names vary — try multiple key variants
            net_foreign_buy = _safe_float(
                row.get("NonRegularForeignNetBuy")
                or row.get("ForeignNetBuy")
                or row.get("NetForeignBuy")
            )
            foreign_buy = _safe_float(row.get("ForeignBuyValue") or row.get("NonRegularForeignBuy"))
            foreign_sell = _safe_float(row.get("ForeignSellValue") or row.get("NonRegularForeignSell"))
            net_vol = int(_safe_float(row.get("ForeignNetVolume") or row.get("NetForeignVolume"), 0))

            ForeignFlow.objects.update_or_create(
                instrument=instrument,
                trading_date=target_date,
                defaults={
                    "net_foreign_buy": net_foreign_buy,
                    "net_foreign_volume": net_vol,
                    "foreign_buy_value": foreign_buy,
                    "foreign_sell_value": foreign_sell,
                },
            )

            # Recompute rolling 5-day signal
            lookback = target_date - timedelta(days=7)
            recent_flows = list(
                ForeignFlow.objects.filter(instrument=instrument, trading_date__gte=lookback)
                .order_by("trading_date")
                .values_list("net_foreign_buy", flat=True)
            )
            signal = adapter.compute_foreign_signal(recent_flows)

            # Update signal on all recent rows for consistency
            ForeignFlow.objects.filter(instrument=instrument, trading_date=target_date).update(signal=signal)

            synced += 1

        except Exception as exc:  # noqa: BLE001
            errors.append(f"{instrument.symbol}: {exc}")

    log.info("Foreign flow sync done: %d synced, %d skipped, %d errors", synced, skipped, len(errors))
    return {"synced": synced, "skipped": skipped, "errors": errors, "date": date_str}
