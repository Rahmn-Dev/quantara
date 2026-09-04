from celery import shared_task
from decimal import Decimal
from datetime import timedelta
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.utils import timezone

from .evaluation import evaluate_predictions
from .market_data import YahooMarketData
from .models import Candle, DemoAccount, DemoOrder, DemoPosition, Instrument, PerformanceSnapshot, TradePlan
from .scanner import scan_market
from .services import broadcast_plans

# Phase 1-4 sync imports
from .broker_flow_sync import sync_broker_flows
from .foreign_flow_sync import sync_foreign_flows
from .fundamental_sync import sync_fundamentals
from .risk_screens import sync_audit_risk, sync_dilution_watch


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
    daily = scan_market(decision_window="CLOSE_FINAL", strategy_profile="NEXT_DAY")
    swing = scan_market(decision_window="CLOSE_FINAL", strategy_profile="SWING", sync=False)
    return {"daily_scanned": daily.instruments_scanned, "swing_scanned": swing.instruments_scanned,
            "paper_orders": auto_paper_trade_plans("CLOSE_FINAL")}


@shared_task
def build_open_plan():
    run = scan_market(decision_window="OPEN_0930", strategy_profile="NEXT_DAY")
    return {"scanned": run.instruments_scanned, "paper_orders": auto_paper_trade_plans("OPEN_0930")}


@shared_task
def build_midday_plan():
    run = scan_market(decision_window="MIDDAY_1130", strategy_profile="NEXT_DAY")
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
    strategy = plans.first().strategy if plans.exists() else None
    performance = (
        PerformanceSnapshot.objects.filter(strategy=strategy).order_by("-computed_at").first()
        if strategy else None
    )
    edge_validated = bool(
        performance and performance.trades >= 100
        and performance.profit_factor >= 1.2 and performance.expectancy > 0
    )
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
    plan_instruments = list(Instrument.objects.filter(tradeplan__trading_date=timezone.localdate()).distinct())
    paper_instruments = list(Instrument.objects.filter(demoposition__status="OPEN").distinct())
    latest_daily = Candle.objects.filter(instrument=OuterRef("pk"), interval="1d").order_by("-timestamp")
    liquid_ids = list(Instrument.objects.filter(is_active=True).annotate(
        latest_volume=Subquery(latest_daily.values("volume")[:1])
    ).exclude(latest_volume=None).order_by("-latest_volume").values_list("id", flat=True)[:240])
    cursor = int(cache.get("intraday-rotation-cursor", 0)) % max(1, len(liquid_ids))
    batch_ids = liquid_ids[cursor:cursor + 8]
    if len(batch_ids) < 8:
        batch_ids += liquid_ids[:8 - len(batch_ids)]
    cache.set("intraday-rotation-cursor", cursor + 8, None)
    instruments = {item.id: item for item in plan_instruments}
    instruments.update({item.id: item for item in paper_instruments})
    instruments.update({item.id: item for item in Instrument.objects.filter(id__in=batch_ids)})
    synced = 0
    for instrument in instruments.values():
        try:
            provider.sync(instrument, period="5d", interval="5m")
            synced += 1
        except Exception:
            continue
    validate_live_setups.delay()
    auto_close_paper_positions.delay()
    return synced


@shared_task
@transaction.atomic
def auto_close_paper_positions():
    """Enforce stop, target, and time expiry for simulated positions."""
    now = timezone.localtime()
    if now.weekday() >= 5:
        return "non-trading day; no close"
    today = now.date()
    cutoff_minute = 15 * 60 + (40 if now.weekday() == 4 else 45)
    current_minute = now.hour * 60 + now.minute
    closed = []
    positions = DemoPosition.objects.select_for_update().filter(status="OPEN").select_related(
        "account", "instrument", "trade_plan"
    )
    for position in positions:
        plan = position.trade_plan
        if not plan:
            continue
        latest = Candle.objects.filter(
            instrument=position.instrument, interval="5m"
        ).order_by("-timestamp").first()
        if (not latest or timezone.localdate(latest.timestamp) != today
                or latest.timestamp <= position.opened_at):
            continue
        strategy = plan.strategy
        reason, fill = None, None
        # If stop and target occur inside the same bar, assume stop first. That
        # conservative ordering avoids optimistic OHLC backfill.
        if latest.low <= plan.stop_loss:
            reason = "STOP_LOSS"
            fill = min(Decimal(latest.open), Decimal(plan.stop_loss)) * Decimal("0.999")
        elif latest.high >= plan.take_profit:
            reason = "TAKE_PROFIT"
            fill = Decimal(plan.take_profit) * Decimal("0.999")
        else:
            is_daily = strategy in {"next_day", "momentum"}
            elapsed_sessions = (
                Candle.objects.filter(instrument=position.instrument, interval="1d",
                                      timestamp__date__gt=plan.trading_date)
                .values("timestamp__date").distinct().count()
            )
            swing_expired = strategy == "swing_5d" and elapsed_sessions >= 5
            if current_minute >= cutoff_minute and (is_daily or swing_expired):
                reason = "TIME_EXIT_DAILY" if is_daily else "TIME_EXIT_SWING"
                fill = Decimal(latest.close) * Decimal("0.999")
        if not reason:
            continue
        shares = position.shares
        proceeds = fill * shares
        exit_fee = proceeds * Decimal("0.0025")
        pnl = proceeds - exit_fee - position.entry_price * shares - position.entry_fee
        position.exit_price = fill; position.exit_fee = exit_fee; position.realized_pnl = pnl
        position.closed_at = timezone.now(); position.status = "CLOSED"; position.save()
        account = position.account; account.cash += proceeds - exit_fee; account.realized_pnl += pnl
        account.save(update_fields=["cash", "realized_pnl", "updated_at"])
        DemoOrder.objects.create(
            account=account, instrument=position.instrument, trade_plan=plan, position=position,
            side="SELL", status=DemoOrder.Status.FILLED,
            requested_lots=shares // 100, filled_lots=shares // 100,
            reference_price=latest.close, fill_price=fill, slippage_percent=0.001,
            fee=exit_fee, filled_at=timezone.now(), reason=reason,
            metadata={
                "entry_price": float(position.entry_price), "allocated_entry_fee": float(position.entry_fee),
                "realized_pnl": float(pnl),
                "net_return": float(pnl / (position.entry_price * shares)) if position.entry_price else 0,
                "partial_close": False, "trigger_candle": latest.timestamp.isoformat(),
            },
        )
        closed.append(f"{position.instrument.symbol}:{reason}")
    return {"closed": closed, "count": len(closed)}


@shared_task
def score_predictions():
    return evaluate_predictions()


# ---------------------------------------------------------------------------
# Phase 1 — Broker Flow / Bandarmologi
# ---------------------------------------------------------------------------

@shared_task
def sync_broker_flows_task(trading_date: str | None = None) -> dict:
    """
    Sync broker flow data (CR1, CR3, CR5, institutional score) for all active
    instruments. Runs during market hours: 09:00, 12:00, 16:00 WIB.
    """
    return sync_broker_flows(trading_date=trading_date)


# ---------------------------------------------------------------------------
# Phase 2 — Financial Fundamentals
# ---------------------------------------------------------------------------

@shared_task
def sync_fundamentals_task(year: int | None = None, quarter: int = 4) -> dict:
    """
    Sync annual financial ratios (PER, PBV, ROE, DER, EPS) for all listed stocks.
    Runs weekly on Sunday 06:00 WIB.
    """
    return sync_fundamentals(year=year, quarter=quarter)


# ---------------------------------------------------------------------------
# Phase 3 — Foreign Flow Radar
# ---------------------------------------------------------------------------

@shared_task
def sync_foreign_flows_task(trading_date: str | None = None) -> dict:
    """
    Sync net foreign buy/sell from IDX StockSummary + compute rolling 5-day signal.
    Runs daily at 16:30 WIB (after market close).
    """
    return sync_foreign_flows(trading_date=trading_date)


# ---------------------------------------------------------------------------
# Phase 4 — Audit Risk + Dilution Watch
# ---------------------------------------------------------------------------

@shared_task
def sync_risk_screens_task() -> dict:
    """
    Sync audit opinions and dilutive corporate actions for all active instruments.
    Updates Instrument.audit_risky + Instrument.has_recent_dilution flags.
    Runs daily at 17:00 WIB (after market close).
    """
    audit_result = sync_audit_risk()
    dilution_result = sync_dilution_watch()
    return {"audit": audit_result, "dilution": dilution_result}
