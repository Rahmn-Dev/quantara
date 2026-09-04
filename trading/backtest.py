from dataclasses import dataclass

import numpy as np

from .ml import FEATURES, _fit_time_calibrated, training_frame
from .models import PerformanceSnapshot
from .strategy_profiles import get_profile


@dataclass(frozen=True)
class BacktestReport:
    trades: int
    win_rate: float
    profit_factor: float
    expectancy: float
    max_drawdown: float


def _select(frame, threshold, max_positions):
    """Apply only rules measurable when a live decision is made."""
    eligible = frame[
        (frame["probability"] >= threshold)
        & (frame["rsi_14"] < 70)
        & (frame["sma20_distance"] < 0.12)
        & (frame["bollinger_position"] < 1.10)
        & (frame["consecutive_green"] < 4)
        & (frame["rvol"] >= 0.80)
    ]
    return (
        eligible.sort_values(["timestamp", "probability"], ascending=[True, False])
        .groupby("timestamp").head(max_positions).dropna(subset=["trade_return"])
    )


def _metrics(selected):
    if selected.empty:
        return BacktestReport(0, 0, 0, 0, 0), []
    returns = selected["trade_return"].astype(float)
    daily = selected.groupby("timestamp")["trade_return"].mean().sort_index()
    equity = (1 + daily.clip(lower=-0.25, upper=0.25)).cumprod()
    drawdown = equity / equity.cummax() - 1
    gains = returns[returns > 0].sum()
    losses = abs(returns[returns < 0].sum())
    report = BacktestReport(
        len(selected), round(float((returns > 0).mean()), 4),
        round(float(gains / losses), 3) if losses else 99.0,
        round(float(returns.mean()), 5), round(float(drawdown.min()), 4),
    )
    step = max(1, len(equity) // 200)
    return report, [round(float(value), 5) for value in equity.iloc[::step]]


def run_model_backtest(*, profile="NEXT_DAY", buy_fee=0.0015, sell_fee=0.0025,
                       slippage=0.001, max_positions=3) -> BacktestReport:
    """Audit the live model on an untouched final 20% chronological test set."""
    profile_name = profile.upper()
    config = get_profile(profile_name)
    horizon = config["horizon_days"]
    if horizon < 1:
        raise ValueError("SCALP needs an intraday 1m/5m backtest dataset")
    frame = training_frame(horizon)
    dates = frame.timestamp.drop_duplicates().sort_values()
    if len(frame) < 1000 or len(dates) < 100:
        raise ValueError("Insufficient daily history for an anchored audit")

    validation_start = dates.iloc[int(len(dates) * 0.70)]
    test_start = dates.iloc[int(len(dates) * 0.80)]
    train = frame[frame.timestamp < validation_start]
    validation = frame[(frame.timestamp >= validation_start) & (frame.timestamp < test_start)].copy()
    test = frame[frame.timestamp >= test_start].copy()
    model, calibration_start = _fit_time_calibrated(train, max_iter=200)
    friction = buy_fee + sell_fee + 2 * slippage
    for sample in (validation, test):
        sample["probability"] = model.predict_proba(sample[FEATURES])[:, 1]
        grouped = sample.groupby("instrument_id", group_keys=False)
        sample["trade_return"] = grouped["close"].shift(-horizon) / grouped["open"].shift(-1) - 1 - friction

    threshold_rows = []
    for threshold in np.arange(0.48, 0.61, 0.02):
        metrics, _ = _metrics(_select(validation, float(threshold), max_positions))
        # Fifteen validation trades is the minimum usable threshold evidence here;
        # production activation still requires a much larger OOS sample below.
        valid = metrics.trades >= 15 and metrics.max_drawdown >= -0.20 and metrics.expectancy > 0
        # Optimize return per unit of observed peak-to-trough risk, not raw hit
        # rate or expectancy. This intentionally prefers a stricter, smoother gate.
        risk = max(abs(metrics.max_drawdown), 0.01)
        score = metrics.expectancy / risk if valid else -np.inf
        threshold_rows.append((score, float(threshold), metrics))
    best_score, selected_threshold, validation_metrics = max(threshold_rows, key=lambda row: row[0])
    if not np.isfinite(best_score):
        selected_threshold = config["min_probability"]

    report, curve = _metrics(_select(test, selected_threshold, max_positions))
    PerformanceSnapshot.objects.create(
        strategy=config["db_strategy"], trades=report.trades, win_rate=report.win_rate,
        profit_factor=report.profit_factor, expectancy=report.expectancy,
        max_drawdown=report.max_drawdown, equity_curve=curve,
        parameters={
            "profile": profile_name, "method": "anchored_out_of_sample_model_audit",
            "train_end": str(validation_start), "test_start": str(test_start),
            "calibration_start": calibration_start,
            "selected_probability": round(selected_threshold, 2),
            "validation_trades": validation_metrics.trades,
            "validation_profit_factor": validation_metrics.profit_factor,
            "validation_drawdown": validation_metrics.max_drawdown,
            "holding_days": horizon, "max_positions_per_day": max_positions,
            "buy_fee": buy_fee, "sell_fee": sell_fee, "slippage_each_side": slippage,
            "filters": "RSI<70, SMA20 distance<12%, Bollinger<1.10, green streak<4, RVOL>=0.8",
            "survivorship_bias_free": False,
        },
    )
    return report


def run_momentum_backtest(**kwargs) -> BacktestReport:
    """Compatibility entry point; now audits the real NEXT_DAY model."""
    return run_model_backtest(profile="NEXT_DAY", **kwargs)
