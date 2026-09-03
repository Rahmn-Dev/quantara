from celery import shared_task
from decimal import Decimal
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .evaluation import evaluate_predictions
from .market_data import YahooMarketData
from .models import Candle, DemoAccount, DemoOrder, DemoPosition, PerformanceSnapshot, TradePlan
from .scanner import scan_market
from .services import broadcast_plans


def market_collection_active(now=None, preopen_minutes=3):
    now = timezone.localtime(now or timezone.now())
    if now.weekday() >= 5:
        return False
    minute = now.hour * 60 + now.minute
    first_end = 11 * 60 + 30 if now.weekday() == 4 else 12 * 60
    second_start = 14 * 60 if now.weekday() == 4 else 13 * 60 + 30
    return (9 * 60 - preopen_minutes <= minute <= first_end) or (second_start - preopen_minutes <= minute <= 15 * 60 + 49)


@shared_task
def build_daily_plan():
    run = scan_market(decision_window="CLOSE_FINAL")
    return {"scanned": run.instruments_scanned, "paper_orders": auto_paper_trade_plans("CLOSE_FINAL")}


@shared_task
def build_open_plan():
    run = scan_market(decision_window="OPEN_0930")
    return {"scanned": run.instruments_scanned, "paper_orders": auto_paper_trade_plans("OPEN_0930")}


@shared_task
def build_midday_plan():
    run = scan_market(decision_window="MIDDAY_1130")
    return {"scanned": run.instruments_scanned, "paper_orders": auto_paper_trade_plans("MIDDAY_1130")}


@transaction.atomic
def auto_paper_trade_plans(decision_window):
    """Track top picks automatically without presenting them as validated live trades."""
    if not settings.AUTO_PAPER_TRADING["enabled"]:
        return 0
    account, _ = DemoAccount.objects.select_for_update().get_or_create(pk=1)
    plans = (TradePlan.objects.filter(trading_date=timezone.localdate(), decision_window=decision_window)
             .select_related("instrument").order_by("-ranking_score")[:settings.AUTO_PAPER_TRADING["top_n"]])
    filled = 0
    performance = PerformanceSnapshot.objects.order_by("-computed_at").first()
    edge_validated = bool(performance and performance.profit_factor >= 1.2 and performance.expectancy > 0)
    for plan in plans:
        if DemoOrder.objects.filter(trade_plan=plan, side="BUY").exists():
            continue
        # Do not stack another automatic position in a symbol the user already tracks.
        if account.positions.filter(instrument=plan.instrument, status="OPEN").exists():
            continue
        candle = Candle.objects.filter(instrument=plan.instrument, interval="5m").order_by("-timestamp").first()
        if candle is None:
            candle = Candle.objects.filter(instrument=plan.instrument, interval="1d").order_by("-timestamp").first()
        if candle is None:
            continue
        reference = Decimal(candle.close)
        liquidity = float(plan.indicators.get("liquidity_score", 50))
        slippage = Decimal(str(min(0.005, max(0.001, 0.004 - liquidity / 25000))))
        fill_price = reference * (Decimal("1") + slippage)
        risk_lots = max(1, plan.position_size // 100)
        affordable_lots = int(account.cash / (fill_price * Decimal("100") * Decimal("1.0015")))
        lots = min(risk_lots, affordable_lots)
        expires_at = timezone.now() + timedelta(minutes=settings.AUTO_PAPER_TRADING["expiry_minutes"])
        order = DemoOrder.objects.create(
            account=account, instrument=plan.instrument, trade_plan=plan, requested_lots=max(1, risk_lots),
            reference_price=reference, expires_at=expires_at, slippage_percent=float(slippage),
            reason="validated READY" if edge_validated and plan.status == "READY" else "automatic research tracking; edge not validated",
            metadata={"decision_window": decision_window, "plan_status": plan.status, "profit_factor_gate_passed": edge_validated},
        )
        if lots < 1:
            order.status = DemoOrder.Status.REJECTED; order.reason = "paper cash insufficient"; order.save()
            continue
        shares = lots * 100
        fee = fill_price * shares * Decimal("0.0015")
        position = DemoPosition.objects.create(account=account, instrument=plan.instrument, trade_plan=plan,
                                               shares=shares, entry_price=fill_price, entry_fee=fee)
        account.cash -= fill_price * shares + fee
        order.position = position; order.status = DemoOrder.Status.FILLED; order.filled_lots = lots
        order.fill_price = fill_price; order.fee = fee; order.filled_at = timezone.now(); order.save()
        filled += 1
    account.save(update_fields=["cash", "updated_at"])
    return filled


@shared_task
def validate_live_setups():
    if not market_collection_active():
        return "market closed; validator idle"
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
    if not market_collection_active():
        return "market closed; collector idle"
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
