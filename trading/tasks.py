from celery import shared_task
from django.utils import timezone

from .evaluation import evaluate_predictions
from .market_data import YahooMarketData
from .models import Candle, TradePlan
from .scanner import scan_market
from .services import broadcast_plans


@shared_task
def build_daily_plan():
    return scan_market(decision_window="CLOSE_FINAL").instruments_scanned


@shared_task
def build_open_plan():
    return scan_market(decision_window="OPEN_0930").instruments_scanned


@shared_task
def build_midday_plan():
    return scan_market(decision_window="MIDDAY_1130").instruments_scanned


@shared_task
def validate_live_setups():
    plans = TradePlan.objects.filter(trading_date=timezone.localdate()).select_related("instrument")
    updated = 0
    for plan in plans:
        bars = list(Candle.objects.filter(instrument=plan.instrument, interval="5m").order_by("-timestamp")[:21])
        if len(bars) < 5:
            continue
        latest, history = bars[0], bars[1:]
        total_volume = sum(bar.volume for bar in bars)
        vwap = sum(float((bar.high + bar.low + bar.close) / 3) * bar.volume for bar in bars) / max(total_volume, 1)
        median_volume = sorted(bar.volume for bar in history)[len(history) // 2] or 1
        intraday_checks = {"entry_zone_live": plan.entry_low <= latest.close <= plan.entry_high,
                           "intraday_vwap": float(latest.close) >= vwap,
                           "intraday_volume": latest.volume >= median_volume * 1.2,
                           "breakout": latest.close >= max(bar.high for bar in history),
                           "spread_verified": False}
        plan.checks = {**plan.checks, **intraday_checks}
        plan.status = "READY" if all(plan.checks.values()) else ("SETUP" if sum(intraday_checks.values()) >= 3 else "WATCH")
        plan.save(update_fields=["checks", "status", "updated_at"])
        updated += 1
    broadcast_plans()
    return f"validated {updated}; spread vetoed until an order-book feed is connected"


@shared_task
def collect_intraday_candidates():
    provider = YahooMarketData()
    plans = TradePlan.objects.filter(trading_date=timezone.localdate()).select_related("instrument")
    synced = 0
    for plan in plans:
        try:
            provider.sync(plan.instrument, period="5d", interval="5m")
            synced += 1
        except Exception:
            continue
    validate_live_setups.delay()
    return synced


@shared_task
def score_predictions():
    return evaluate_predictions()
