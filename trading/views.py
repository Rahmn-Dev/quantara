from django.db.models import OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .market_data import YahooMarketData
from .models import (
    Candle,
    Instrument,
    MarketRegime,
    ModelRun,
    PerformanceSnapshot,
    PredictionRecord,
    ScanRun,
    TradePlan,
    DemoAccount,
    DemoOrder,
    DemoPosition,
)
from .scanner import scan_market
from .serializers import TradePlanSerializer
from .services import generate_demo_plans


def _fetch_live_prices(symbols):
    """Batch Yahoo intraday lookup; callers provide their own short cache."""
    import yfinance as yf

    clean = list(dict.fromkeys(s.upper().strip() for s in symbols if s.strip()))[:50]
    if not clean:
        return {}
    tickers = [f"{symbol}.JK" for symbol in clean]
    frame = yf.download(
        tickers,
        period="1d",
        interval="1m",
        auto_adjust=True,
        progress=False,
        threads=True,
        timeout=12,
        group_by="ticker",
    )
    prices = {}
    for symbol, ticker in zip(clean, tickers):
        try:
            series = frame[ticker]["Close"].dropna() if len(tickers) > 1 else frame["Close"].dropna()
            if not series.empty:
                prices[symbol] = {"price": float(series.iloc[-1]), "market_time": series.index[-1]}
        except (KeyError, TypeError, IndexError):
            continue
    return prices


def dashboard(request):
    return render(request, "trading/dashboard.html")


def market_session():
    now = timezone.localtime()
    minutes = now.hour * 60 + now.minute
    if now.weekday() >= 5:
        return "MARKET_CLOSED"
    friday = now.weekday() == 4
    session_one_close = 11 * 60 + 30 if friday else 12 * 60
    session_two_open = 14 * 60 if friday else 13 * 60 + 30
    if minutes < 9 * 60:
        return "PRE_OPEN"
    if minutes <= session_one_close:
        return "MORNING_SESSION"
    if minutes < session_two_open:
        return "SESSION_BREAK"
    if minutes <= 15 * 60 + 49:
        return "AFTERNOON_SESSION"
    return "TOMORROW_PLAN"


@api_view(["GET"])
def today(request):
    trading_date = timezone.localdate()
    base_plans = TradePlan.objects.filter(trading_date=trading_date)
    available_windows = list(base_plans.order_by().values_list("decision_window", flat=True).distinct())
    requested_window = request.GET.get("window", "").upper()
    preferred = ["CLOSE_FINAL", "MIDDAY_1130", "OPEN_0930", "LEGACY"]
    selected_window = requested_window if requested_window in available_windows else next((item for item in preferred if item in available_windows), "LEGACY")
    plans = list(base_plans.filter(decision_window=selected_window).select_related("instrument"))

    regime = MarketRegime.objects.order_by("-observed_at").first()
    scan = ScanRun.objects.order_by("-started_at").first()
    return Response(
        {
            "date": str(trading_date),
            "regime": regime.state if regime else "BULLISH",
            "risk_mode": "NORMAL",
            "session": market_session(),
            "selected_window": selected_window,
            "available_windows": available_windows,
            "data": {
                "source": scan.source if scan else "demo",
                "freshest_candle_at": scan.freshest_candle_at if scan else None,
                "status": scan.status if scan else "NO_REAL_SCAN",
                "errors": len(scan.errors) if scan else 0,
            },
            "model": ModelRun.objects.order_by("-trained_at")
            .values("name", "trained_at", "samples", "metrics")
            .first(),
            "plans": TradePlanSerializer(plans, many=True).data,
        }
    )


@api_view(["POST"])
def demo_scan(request):
    plans = generate_demo_plans(float(request.data.get("equity", 100_000_000)))
    return Response({"created": len(plans)})


@api_view(["POST"])
def real_scan(request):
    limits = settings.QUANT_LIMITS
    requested_gate = float(request.data.get("min_ml_probability", limits["min_ml_probability"]))
    if requested_gate not in {0.50, 0.55, 0.60, 0.65}:
        return Response({"error": "ML gate must be 0.50, 0.55, 0.60, or 0.65"}, status=400)
    min_rr = float(request.data.get("min_risk_reward", limits["min_risk_reward"]))
    max_risk = float(request.data.get("max_risk_per_trade", limits["max_risk_per_trade"]))
    max_daily_loss = float(request.data.get("max_daily_loss", limits["max_daily_loss"]))
    min_score = float(request.data.get("min_signal_score", limits["min_signal_score"]))
    min_profit_factor = float(request.data.get("min_profit_factor", limits["min_profit_factor"]))
    if not 1.0 <= min_rr <= 3.0:
        return Response({"error": "Minimum risk/reward must be between 1.0 and 3.0"}, status=400)
    if not 0.001 <= max_risk <= 0.02:
        return Response({"error": "Risk per trade must be between 0.1% and 2.0%"}, status=400)
    if not 0.005 <= max_daily_loss <= 0.05:
        return Response({"error": "Daily loss limit must be between 0.5% and 5.0%"}, status=400)
    if not 50 <= min_score <= 90:
        return Response({"error": "Quant score gate must be between 50 and 90"}, status=400)
    if not 1.0 <= min_profit_factor <= 2.0:
        return Response({"error": "Profit Factor gate must be between 1.0 and 2.0"}, status=400)
    run = scan_market(
        equity=float(request.data.get("equity", 100_000_000)),
        sync=not bool(request.data.get("offline", False)),
        verbose=bool(request.data.get("verbose", False)),
        min_ml_probability=requested_gate,
        min_rr=min_rr,
        max_risk=max_risk,
        max_daily_loss=max_daily_loss,
        min_score=min_score,
        min_profit_factor=min_profit_factor,
    )
    return Response(
        {
            "id": run.id,
            "status": run.status,
            "scanned": run.instruments_scanned,
            "errors": run.errors,
        }
    )


@api_view(["POST"])
def plan_insight(request, plan_id):
    plan = get_object_or_404(TradePlan.objects.select_related("instrument"), pk=plan_id)
    generated = False
    if not plan.commentary:
        from .llm import NineRouterClient

        payload = {
            "symbol": plan.instrument.symbol,
            "score": plan.score,
            "confidence": plan.confidence,
            "entry_low": plan.entry_low,
            "entry_high": plan.entry_high,
            "stop_loss": plan.stop_loss,
            "take_profit": plan.take_profit,
            "risk_reward": plan.risk_reward,
            "position_size": plan.position_size,
            "status": plan.status,
            "checks": plan.checks,
            "veto_reasons": plan.veto_reasons,
        }
        try:
            plan.commentary = NineRouterClient().explain(payload)
            plan.save(update_fields=["commentary", "updated_at"])
            generated = True
        except Exception as exc:  # noqa: BLE001 - expose a controlled API error
            return Response({"error": f"AI Insight gagal: {exc}"}, status=503)
    return Response({"plan_id": plan.id, "commentary": plan.commentary, "cached": not generated})


@api_view(["GET"])
def chart(request, symbol):
    requested_range = request.GET.get("range", "1y")
    range_limits = {"5d": 5, "1mo": 23, "3mo": 66, "1y": 260}
    if requested_range == "5y":
        try:
            frame = YahooMarketData().fetch(symbol, period="5y", interval="1d")
            return Response(
                [
                    {
                        "time": index.to_pydatetime(),
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "volume": int(row.get("Volume", 0)),
                    }
                    for index, row in frame.iterrows()
                ]
            )
        except Exception as exc:  # noqa: BLE001 - controlled provider failure
            return Response({"error": str(exc)}, status=503)
    limit = range_limits.get(requested_range, 260)
    candles = Candle.objects.filter(instrument__symbol=symbol, interval="1d").order_by(
        "-timestamp"
    )[:limit]
    return Response(
        list(
            reversed(
                [
                    {
                        "time": row.timestamp,
                        "open": row.open,
                        "high": row.high,
                        "low": row.low,
                        "close": row.close,
                        "volume": row.volume,
                    }
                    for row in candles
                ]
            )
        )
    )


@api_view(["GET"])
def scanner_list(request):
    search = request.GET.get("q", "").upper().strip()
    status = request.GET.get("status", "").upper().strip()
    page = max(int(request.GET.get("page", 1)), 1)
    size = min(max(int(request.GET.get("size", 50)), 10), 100)
    latest_plan = TradePlan.objects.filter(
        instrument=OuterRef("pk"), trading_date=timezone.localdate()
    ).order_by("-score")
    latest_candle = Candle.objects.filter(instrument=OuterRef("pk"), interval="1d").order_by(
        "-timestamp"
    )
    queryset = Instrument.objects.filter(is_active=True).annotate(
        plan_status=Subquery(latest_plan.values("status")[:1]),
        plan_score=Coalesce(Subquery(latest_plan.values("score")[:1]), 0.0),
        plan_confidence=Coalesce(Subquery(latest_plan.values("confidence")[:1]), 0.0),
        last_price=Subquery(latest_candle.values("close")[:1]),
        last_time=Subquery(latest_candle.values("timestamp")[:1]),
    )
    if search:
        queryset = queryset.filter(symbol__icontains=search)
    if status:
        queryset = queryset.filter(plan_status=status)
    queryset = queryset.order_by("-plan_score", "symbol")
    total = queryset.count()
    rows = queryset[(page - 1) * size : page * size]
    return Response(
        {
            "page": page,
            "size": size,
            "total": total,
            "results": [
                {
                    "symbol": row.symbol,
                    "name": row.name,
                    "sector": row.sector,
                    "price": row.last_price,
                    "updated_at": row.last_time,
                    "status": row.plan_status or "UNRANKED",
                    "score": row.plan_score,
                    "confidence": row.plan_confidence,
                }
                for row in rows
            ],
        }
    )


@api_view(["GET"])
def market_ticker(request):
    """Largest daily movers, overlaid with the latest best-effort intraday price."""
    now = timezone.localtime()
    minute = now.hour * 60 + now.minute
    first_end = 11 * 60 + 30 if now.weekday() == 4 else 12 * 60
    second_start = 14 * 60 if now.weekday() == 4 else 13 * 60 + 30
    market_active = now.weekday() < 5 and ((8 * 60 + 57 <= minute <= first_end) or (second_start - 3 <= minute <= 15 * 60 + 49))
    cache_key = "market-ticker-live" if market_active else "market-ticker-final"
    cached = cache.get(cache_key)
    if cached:
        return Response(cached)
    daily = Candle.objects.filter(instrument=OuterRef("pk"), interval="1d").order_by(
        "-timestamp"
    )
    rows = Instrument.objects.filter(is_active=True).annotate(
        latest_close=Subquery(daily.values("close")[:1]),
        previous_close=Subquery(daily.values("close")[1:2]),
        latest_time=Subquery(daily.values("timestamp")[:1]),
    )
    movers = []
    for row in rows.iterator():
        if row.latest_close is None or not row.previous_close:
            continue
        change = float((row.latest_close / row.previous_close - 1) * 100)
        movers.append(
            {
                "symbol": row.symbol,
                "price": float(row.latest_close),
                "change_percent": round(change, 2),
                "updated_at": row.latest_time,
                "previous_close": float(row.previous_close),
            }
        )
    movers.sort(key=lambda item: abs(item["change_percent"]), reverse=True)
    movers = movers[:40]
    live = {}
    if market_active:
        try:
            live = _fetch_live_prices([item["symbol"] for item in movers])
        except Exception:  # noqa: BLE001 - stored daily tape remains usable
            live = {}
    for item in movers:
        quote = live.get(item["symbol"])
        if quote:
            item["price"] = quote["price"]
            item["updated_at"] = quote["market_time"]
            item["change_percent"] = round((quote["price"] / item["previous_close"] - 1) * 100, 2)
        item.pop("previous_close", None)
    payload = {"source": "Yahoo intraday best-effort" if market_active else "stored final close", "market_active": market_active, "results": movers}
    cache.set(cache_key, payload, 10 if market_active else 3600)
    return Response(payload)


@api_view(["GET"])
def live_prices(request):
    symbols = [value for value in request.GET.get("symbols", "").split(",") if value]
    symbols = list(dict.fromkeys(symbol.upper().strip() for symbol in symbols))[:30]
    cache_key = "live-prices:" + ",".join(sorted(symbols))
    prices = cache.get(cache_key)
    if prices is None:
        try:
            prices = _fetch_live_prices(symbols)
            from .models import Candle
            for symbol in symbols:
                if symbol in prices:
                    candles = list(Candle.objects.filter(instrument__symbol=symbol, interval="1d").order_by("-timestamp")[:1])
                    if candles:
                        import datetime
                        today_midnight = timezone.make_aware(datetime.datetime.combine(timezone.localdate(), datetime.time.min))
                        prev_candle = Candle.objects.filter(instrument__symbol=symbol, interval="1d", timestamp__lt=today_midnight).order_by("-timestamp").first()
                        if prev_candle:
                            prices[symbol]["previous_close"] = float(prev_candle.close)
                        else:
                            prices[symbol]["previous_close"] = float(candles[0].close)
        except Exception:  # noqa: BLE001 - UI retains last known daily values
            prices = {}
        cache.set(cache_key, prices, 3)
    return Response({"source": "Yahoo intraday best-effort", "delayed": True, "prices": prices})


def _paper_price(instrument):
    candle = Candle.objects.filter(instrument=instrument, interval="1d").order_by("-timestamp").first()
    return candle.close if candle else None


@api_view(["GET"])
def demo_account(request):
    account, _ = DemoAccount.objects.get_or_create(pk=1)
    positions, market_value, unrealized = [], Decimal("0"), Decimal("0")
    for position in account.positions.filter(status="OPEN").select_related("instrument", "trade_plan"):
        price = _paper_price(position.instrument) or position.entry_price
        value = price * position.shares
        pnl = (price - position.entry_price) * position.shares - position.entry_fee
        market_value += value; unrealized += pnl
        positions.append({"id": position.id, "symbol": position.instrument.symbol, "shares": position.shares,
                          "lots": position.shares // 100, "entry_price": position.entry_price,
                          "current_price": price, "market_value": value, "unrealized_pnl": pnl})
    orders = [{"id": order.id, "symbol": order.instrument.symbol, "side": order.side, "status": order.status,
               "requested_lots": order.requested_lots, "filled_lots": order.filled_lots,
               "reference_price": order.reference_price, "fill_price": order.fill_price,
               "slippage_percent": order.slippage_percent, "fee": order.fee, "reason": order.reason,
               "submitted_at": order.submitted_at}
              for order in account.orders.select_related("instrument").all()[:25]]
    return Response({"name": account.name, "starting_cash": account.starting_cash, "cash": account.cash,
                     "market_value": market_value, "equity": account.cash + market_value,
                     "unrealized_pnl": unrealized, "realized_pnl": account.realized_pnl,
                     "fee_assumption": {"buy": 0.0015, "sell": 0.0025}, "positions": positions, "orders": orders})


@api_view(["POST"])
@transaction.atomic
def demo_account_config(request):
    account, _ = DemoAccount.objects.select_for_update().get_or_create(pk=1)
    try:
        starting_cash = Decimal(str(request.data.get("starting_cash")))
    except (TypeError, ValueError, ArithmeticError):
        return Response({"error": "Modal awal tidak valid."}, status=400)
    if starting_cash < Decimal("1000000") or starting_cash > Decimal("10000000000"):
        return Response({"error": "Modal awal harus Rp1 juta–Rp10 miliar."}, status=400)
    account.cash += starting_cash - account.starting_cash
    if account.cash < 0:
        return Response({"error": "Modal tidak dapat lebih kecil dari dana yang sudah dipakai."}, status=409)
    account.starting_cash = starting_cash
    account.save(update_fields=["starting_cash", "cash", "updated_at"])
    return Response({"starting_cash": account.starting_cash, "cash": account.cash})


@api_view(["POST"])
@transaction.atomic
def demo_buy(request, plan_id):
    plan = get_object_or_404(TradePlan.objects.select_related("instrument"), pk=plan_id)
    if plan.status not in {TradePlan.Status.READY, TradePlan.Status.SETUP, TradePlan.Status.WATCH}:
        return Response({"error": "Status ini tidak layak untuk paper test."}, status=409)
    max_lots = max(1, plan.position_size // 100)
    try:
        lots = int(request.data.get("lots", 1))
    except (TypeError, ValueError):
        return Response({"error": "Jumlah lot harus berupa angka bulat."}, status=400)
    if lots < 1 or lots > max_lots:
        return Response({"error": f"Jumlah lot harus 1–{max_lots} sesuai batas risiko."}, status=400)
    shares = lots * 100
    price = _paper_price(plan.instrument)
    if price is None:
        return Response({"error": "Harga pasar belum tersedia."}, status=409)
    if not Decimal(str(plan.entry_low)) <= price <= Decimal(str(plan.entry_high)):
        return Response({"error": "Harga saat ini berada di luar entry zone."}, status=409)
    account, _ = DemoAccount.objects.select_for_update().get_or_create(pk=1)
    fee = price * shares * Decimal("0.0015")
    cost = price * shares + fee
    if account.cash < cost:
        return Response({"error": "Kas paper account tidak cukup."}, status=409)
    position = DemoPosition.objects.create(account=account, instrument=plan.instrument, trade_plan=plan,
                                           shares=shares, entry_price=price, entry_fee=fee)
    DemoOrder.objects.create(
        trade_plan=plan, side="BUY", account=account, instrument=plan.instrument, position=position,
        status=DemoOrder.Status.FILLED, requested_lots=lots, filled_lots=lots,
        reference_price=price, fill_price=price, fee=fee, filled_at=timezone.now(),
        reason="manual paper order", metadata={"plan_status": plan.status},
    )
    account.cash -= cost; account.save(update_fields=["cash", "updated_at"])
    return Response({"id": position.id, "symbol": plan.instrument.symbol, "lots": lots, "fill_price": price}, status=201)


@api_view(["POST"])
@transaction.atomic
def demo_close(request, position_id):
    position = get_object_or_404(DemoPosition.objects.select_for_update().select_related("account", "instrument"), pk=position_id, status="OPEN")
    price = _paper_price(position.instrument)
    if price is None:
        return Response({"error": "Harga pasar belum tersedia."}, status=409)
    try:
        lots = int(request.data.get("lots", position.shares // 100))
    except (TypeError, ValueError):
        return Response({"error": "Jumlah lot tidak valid."}, status=400)
    open_lots = position.shares // 100
    if lots < 1 or lots > open_lots:
        return Response({"error": f"Jumlah lot harus 1–{open_lots}."}, status=400)
    closing_shares = lots * 100
    allocated_entry_fee = position.entry_fee * Decimal(closing_shares) / Decimal(position.shares)
    proceeds = price * closing_shares
    exit_fee = proceeds * Decimal("0.0025")
    pnl = proceeds - exit_fee - position.entry_price * closing_shares - allocated_entry_fee
    if closing_shares == position.shares:
        position.exit_price = price; position.exit_fee = exit_fee; position.realized_pnl = pnl
        position.closed_at = timezone.now(); position.status = "CLOSED"
    else:
        position.shares -= closing_shares
        position.entry_fee -= allocated_entry_fee
    position.save()
    account = position.account; account.cash += proceeds - exit_fee; account.realized_pnl += pnl
    account.save(update_fields=["cash", "realized_pnl", "updated_at"])
    return Response({"id": position.id, "closed_lots": lots, "remaining_lots": position.shares // 100 if position.status == "OPEN" else 0,
                     "exit_price": price, "realized_pnl": pnl})


@api_view(["GET"])
def system_status(request):
    model = ModelRun.objects.order_by("-trained_at").first()
    performance = PerformanceSnapshot.objects.order_by("-computed_at").first()
    evaluated = PredictionRecord.objects.filter(was_correct__isnull=False)
    evaluated_count = evaluated.count()
    correct_count = evaluated.filter(was_correct=True).count()
    auc = float(model.metrics.get("mean_auc", 0.5)) if model else 0.5
    profit_factor = float(performance.profit_factor) if performance else 0.0
    max_drawdown = abs(float(performance.max_drawdown)) if performance else 1.0
    # Conservative composite: journal uses a 10-observation 50/50 prior so a
    # tiny 4/4 record cannot masquerade as a proven 100% engine.
    auc_quality = max(0.0, min(1.0, (auc - 0.5) / 0.15))
    profit_quality = max(0.0, min(1.0, (profit_factor - 1.0) / 0.5))
    drawdown_quality = max(0.0, min(1.0, 1.0 - max_drawdown / 0.30))
    journal_quality = (correct_count + 5) / (evaluated_count + 10)
    engine_quality = round(
        100 * (0.35 * auc_quality + 0.30 * profit_quality + 0.20 * journal_quality + 0.15 * drawdown_quality)
    )
    return Response(
        {
            "universe": Instrument.objects.filter(is_active=True).count(),
            "candles": Candle.objects.count(),
            "engine_quality": {
                "score": engine_quality,
                "grade": "VALIDATED" if engine_quality >= 70 else "DEVELOPING" if engine_quality >= 50 else "EXPERIMENTAL",
                "evaluated": evaluated_count,
                "correct": correct_count,
                "components": {
                    "auc": round(auc_quality * 100),
                    "profit_factor": round(profit_quality * 100),
                    "journal_adjusted": round(journal_quality * 100),
                    "drawdown": round(drawdown_quality * 100),
                },
            },
            "limits": settings.QUANT_LIMITS,
            "model": {
                "name": model.name,
                "trained_at": model.trained_at,
                "samples": model.samples,
                "metrics": model.metrics,
            }
            if model
            else None,
            "backtest": {
                "strategy": performance.strategy,
                "trades": performance.trades,
                "win_rate": performance.win_rate,
                "profit_factor": performance.profit_factor,
                "expectancy": performance.expectancy,
                "max_drawdown": performance.max_drawdown,
                "equity_curve": performance.equity_curve,
                "parameters": performance.parameters,
            }
            if performance
            else None,
        }
    )


@api_view(["GET"])
def prediction_history(request):
    # Keep the journal current whenever stored market data already contains the
    # next trading-day candle. This is idempotent and only touches pending rows.
    from .evaluation import evaluate_predictions

    evaluate_predictions()
    requested_window = request.GET.get("window", "").upper()
    base_records = PredictionRecord.objects.all()
    available_windows = list(base_records.order_by().values_list("decision_window", flat=True).distinct())
    records = base_records
    if requested_window and requested_window != "ALL":
        records = records.filter(decision_window=requested_window)
    records = records.select_related("instrument").order_by("-predicted_at")[:100]
    evaluated = PredictionRecord.objects.filter(was_correct__isnull=False)
    accuracy = evaluated.filter(was_correct=True).count() / evaluated.count() if evaluated else None
    return Response(
        {
            "evaluated": evaluated.count(),
            "accuracy": accuracy,
            "selected_window": requested_window or "ALL",
            "available_windows": available_windows,
            "results": [
                {
                    "symbol": row.instrument.symbol,
                    "signal_date": row.signal_date,
                    "model": row.model_name,
                    "probability": row.model_probability,
                    "quant_score": row.quant_score,
                    "decision": row.decision,
                    "decision_window": row.decision_window,
                    "reference_price": row.reference_price,
                    "realized_price": row.realized_price,
                    "realized_return": row.realized_return,
                    "was_correct": row.was_correct,
                    "evaluated_at": row.evaluated_at,
                    "last_stored_price": (Candle.objects.filter(instrument=row.instrument, interval="1d").order_by("-timestamp").values_list("close", flat=True).first()),
                }
                for row in records
            ],
        }
    )


@api_view(["GET"])
def intraday(request, symbol):
    try:
        frame = YahooMarketData().fetch(symbol, period="5d", interval="5m").tail(300)
        def scalar(value):
            return value.iloc[0] if hasattr(value, "iloc") else value
        return Response(
            {
                "symbol": symbol,
                "source": "Yahoo best-effort",
                "delayed": True,
                "candles": [
                    {
                        "time": index.to_pydatetime(),
                        "open": float(scalar(row["Open"])),
                        "high": float(scalar(row["High"])),
                        "low": float(scalar(row["Low"])),
                        "close": float(scalar(row["Close"])),
                        "volume": int(scalar(row.get("Volume", 0))),
                    }
                    for index, row in frame.iterrows()
                ],
            }
        )
    except Exception as exc:  # noqa: BLE001 - controlled provider failure
        return Response(
            {
                "symbol": symbol,
                "source": "Yahoo best-effort",
                "delayed": True,
                "candles": [],
                "error": str(exc),
            },
            status=503,
        )
