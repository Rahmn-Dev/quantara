from django.conf import settings
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from dataclasses import replace

def broadcast_log(message: str, verbose: bool):
    if not verbose:
        return
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "market",
        {
            "type": "market.update",
            "payload": {"type": "log", "message": message},
        },
    )

def fetch_ai_insights_bg(plans_with_values, verbose):
    import time
    try:
        from .llm import NineRouterClient
        from .models import TradePlan
        client = NineRouterClient()
        
        for plan_id, values, symbol in plans_with_values:
            broadcast_log(f"Requesting AI LLM insight for {symbol} (bg)...", verbose)
            try:
                ai_commentary = client.explain(values)
                TradePlan.objects.filter(id=plan_id).update(commentary=ai_commentary)
                broadcast_log(f"AI Insight saved for {symbol}.", verbose)
            except Exception as exc:
                broadcast_log(f"AI Error for {symbol}: {exc}", verbose)
                TradePlan.objects.filter(id=plan_id).update(commentary=f"Gagal memuat analisa AI: {exc}")
            
            time.sleep(1)  # tiny delay to avoid throttling
        # One UI refresh after the complete batch prevents a WebSocket refresh storm.
        broadcast_plans()
    except Exception as e:
        broadcast_log(f"BG Thread Error: {e}", verbose)



from .engine import create_decision
from .features import build_snapshot
from .market_data import YahooMarketData
from .ml import predict_probability
from .models import (
    Candle,
    Instrument,
    MarketRegime,
    ModelRun,
    PerformanceSnapshot,
    PredictionRecord,
    ScanRun,
    TradePlan,
)
from .services import broadcast_plans
from .evaluation import evaluate_predictions


def scan_market(
    *, equity=100_000_000, sync=True, verbose=False, min_ml_probability=None,
    min_rr=None, max_risk=None, max_daily_loss=None, min_score=None,
    min_profit_factor=None, decision_window=None
):
    if decision_window is None:
        now = timezone.localtime()
        decision_window = "OPEN_0930" if now.hour < 10 else ("MIDDAY_1130" if now.hour < 15 else "CLOSE_FINAL")
    broadcast_log(f"Starting market scan (sync={sync})...", verbose)
    run = ScanRun.objects.create(source="yahoo", interval="1d", decision_window=decision_window)
    provider = YahooMarketData()
    decisions, snapshots, errors, freshest = [], [], [], None
    limits = settings.QUANT_LIMITS
    effective = {
        "min_signal_score": float(min_score if min_score is not None else limits["min_signal_score"]),
        "min_ml_probability": float(min_ml_probability if min_ml_probability is not None else limits["min_ml_probability"]),
        "min_risk_reward": float(min_rr if min_rr is not None else limits["min_risk_reward"]),
        "max_risk_per_trade": float(max_risk if max_risk is not None else limits["max_risk_per_trade"]),
        "max_daily_loss": float(max_daily_loss if max_daily_loss is not None else limits["max_daily_loss"]),
        "min_profit_factor": float(min_profit_factor if min_profit_factor is not None else limits["min_profit_factor"]),
        "equity": float(equity),
        "quant_weights": {"momentum": 0.31, "relative_volume": 0.24, "vwap": 0.17, "volatility": 0.13, "liquidity": 0.15, "broker_flow": 0.0},
    }
    instruments = Instrument.objects.filter(is_active=True)
    regime = "NEUTRAL"
    if not sync:
        cached_regime = MarketRegime.objects.order_by("-observed_at").first()
        regime = cached_regime.state if cached_regime else "NEUTRAL"
    else:
        try:
            broadcast_log("Checking market regime (^JKSE)...", verbose)
            index_frame = provider.fetch("^JKSE", period="1y", interval="1d")
            close = index_frame["Close"]
            sma20, sma50 = close.tail(20).mean(), close.tail(50).mean()
            regime = (
                "BULLISH"
                if close.iloc[-1] > sma20 > sma50
                else ("HIGH_RISK" if close.iloc[-1] < sma20 < sma50 else "NEUTRAL")
            )
            MarketRegime.objects.create(
                observed_at=timezone.now(),
                state=regime,
                score=round(float(close.iloc[-1] / sma50 - 1) * 100, 3),
                notes=["^JKSE close versus 20-day and 50-day moving averages"],
            )
        except Exception as exc:  # noqa: BLE001 - scanner continues in neutral regime
            errors.append(f"^JKSE regime: {exc}")
    for instrument in instruments:
        try:
            broadcast_log(f"Analyzing {instrument.symbol}...", verbose)
            if sync:
                result = provider.sync(instrument)
                if result.latest and (not freshest or result.latest > freshest):
                    freshest = result.latest
            snapshot = build_snapshot(instrument)
            snapshots.append((instrument, snapshot))
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not abort the market scan
            errors.append(f"{instrument.symbol}: {exc}")
    # Cross-sectional percentile is more informative than a score that saturates
    # whenever rupiah turnover is merely large in absolute terms.
    ordered_turnover = sorted(snapshot.median_turnover_20d for _, snapshot in snapshots)
    turnover_count = max(1, len(ordered_turnover) - 1)
    for instrument, snapshot in snapshots:
        percentile = 100 * sum(value < snapshot.median_turnover_20d for value in ordered_turnover) / turnover_count
        snapshot = replace(snapshot, liquidity_score=round(percentile, 2))
        try:
            decision = create_decision(
                snapshot,
                equity=equity,
                daily_pnl_pct=0,
                regime=regime,
                min_score=effective["min_signal_score"], min_rr=effective["min_risk_reward"],
                max_risk=effective["max_risk_per_trade"], max_daily_loss=effective["max_daily_loss"],
            )
            decisions.append((decision, predict_probability(snapshot), snapshot))
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not abort the market scan
            errors.append(f"{instrument.symbol}: {exc}")
    trading_date = timezone.localdate()
    TradePlan.objects.filter(trading_date=trading_date, strategy="momentum", decision_window=decision_window).delete()
    performance = (
        PerformanceSnapshot.objects.filter(strategy="momentum_20d_rvol")
        .order_by("-computed_at")
        .first()
    )
    model_run = ModelRun.objects.order_by("-trained_at").first()
    # Keep one coherent latest snapshot. Seven candidates remain readable in
    # the playbook while giving the user more breadth than the old top-five cap.
    ranked = sorted(
        decisions, key=lambda item: item[0].score * 0.45 + (item[1] or 0.5) * 55, reverse=True
    )[:7]
    
    for decision, ml_probability, snapshot in ranked:
        values = decision.to_dict()
        values.pop("symbol")
        if ml_probability is not None:
            values["confidence"] = round(ml_probability, 3)
            ml_gate = effective["min_ml_probability"]
            values["checks"]["ml_probability"] = ml_probability >= ml_gate
            if ml_probability < ml_gate:
                values["status"] = "WAIT"
                values["veto_reasons"].append(
                    f"ML Probability Below {ml_gate:.0%}"
                )
        if model_run and model_run.metrics.get("mean_auc", 0) < 0.52:
            values["status"] = "WAIT"
            values["checks"]["walk_forward"] = False
            values["veto_reasons"].append("ML Walk-Forward AUC Below 0.52")
        profit_factor_gate = effective["min_profit_factor"]
        if performance and (
            performance.profit_factor < profit_factor_gate or performance.expectancy <= 0
        ):
            values["status"] = "WAIT"
            values["checks"]["validated_edge"] = False
            values["veto_reasons"].append(
                f"Strategy Profit Factor Below {profit_factor_gate:.2f} Or Expectancy Non-Positive"
            )

        # Express useful progression without pretending a watchlist candidate
        # is executable. READY still requires every check, including validation.
        checks = values["checks"]
        if all(checks.values()) and values["position_size"] > 0:
            values["status"] = "READY"
        elif (
            checks.get("signal", False)
            and checks.get("liquidity", False)
            and checks.get("regime", False)
            and checks.get("ml_probability", False)
        ):
            values["status"] = "SETUP"
        elif checks.get("signal", False):
            values["status"] = "WATCH"
        else:
            values["status"] = "REJECT"
            
        broadcast_log(f"Saving TradePlan for {decision.symbol}...", verbose)
        instrument = Instrument.objects.get(symbol=decision.symbol)
        probability_for_rank = ml_probability if ml_probability is not None else 0.5
        ranking_score = round(decision.score * 0.45 + probability_for_rank * 55, 2)
        indicator_evidence = {
            "close": round(snapshot.close, 4), "momentum_20d": round(snapshot.momentum_20d, 6),
            "relative_volume": round(snapshot.relative_volume, 4), "distance_to_vwap": round(snapshot.distance_to_vwap, 6),
            "atr_percent": round(snapshot.atr_percent, 6), "liquidity_score": round(snapshot.liquidity_score, 2),
            "broker_flow_score": round(snapshot.broker_flow_score, 2), "broker_flow_source": "neutral_placeholder_no_broker_feed",
            "gap_percent": round(snapshot.gap_percent, 6), "market_regime": regime,
            "momentum_5d": round(snapshot.momentum_5d, 6), "momentum_60d": round(snapshot.momentum_60d, 6),
            "momentum_120d": round(snapshot.momentum_120d, 6), "volatility_20d": round(snapshot.volatility_20d, 6),
            "distance_to_sma20": round(snapshot.distance_to_sma20, 6), "rsi_14": round(snapshot.rsi_14, 2),
            "bollinger_position": round(snapshot.bollinger_position, 4), "consecutive_green_days": snapshot.consecutive_green_days,
            "volume_climax": round(snapshot.volume_climax, 4), "median_turnover_20d": round(snapshot.median_turnover_20d, 2),
        }
        plan, _ = TradePlan.objects.update_or_create(
            instrument=instrument,
            trading_date=trading_date,
            strategy="momentum",
            decision_window=decision_window,
            defaults={
                **values,
                "ranking_score": ranking_score,
                "indicators": indicator_evidence,
                "scan_settings": effective,
                "commentary": "",
            },
        )
        latest_candle = (
            Candle.objects.filter(instrument=instrument, interval="1d")
            .order_by("-timestamp")
            .first()
        )
        if latest_candle and ml_probability is not None:
            PredictionRecord.objects.update_or_create(
                instrument=instrument,
                signal_date=trading_date,
                model_name=model_run.name if model_run else "unversioned",
                horizon_days=1,
                decision_window=decision_window,
                defaults={
                    "trade_plan": plan,
                    "model_probability": ml_probability,
                    "quant_score": decision.score,
                    "decision": values["status"],
                    "reference_price": latest_candle.close,
                    "evidence": {
                        "indicators": indicator_evidence,
                        "scan_settings": effective,
                        "ranking_score": ranking_score,
                        "decision_window": decision_window,
                        "checks": values["checks"],
                        "veto_reasons": values["veto_reasons"],
                    },
                },
            )
    run.status = ScanRun.Status.COMPLETE if decisions else ScanRun.Status.FAILED
    run.completed_at = timezone.now()
    run.instruments_scanned = len(decisions)
    run.freshest_candle_at = freshest
    run.errors = errors
    run.save()
    # Newly synchronized daily candles can immediately prove yesterday's calls.
    evaluate_predictions()
    broadcast_log(f"Market scan complete. Scanned {run.instruments_scanned} instruments.", verbose)
    broadcast_plans()
    
    return run
