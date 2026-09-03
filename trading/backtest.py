from dataclasses import dataclass

import pandas as pd

from .models import Candle, PerformanceSnapshot


@dataclass(frozen=True)
class BacktestReport:
    trades: int
    win_rate: float
    profit_factor: float
    expectancy: float
    max_drawdown: float


def run_momentum_backtest(*, holding_days=5, fee_rate=0.003) -> BacktestReport:
    """Leakage-safe cross-sectional momentum test using only information at signal time."""
    rows = Candle.objects.filter(interval="1d").values(
        "instrument_id", "timestamp", "close", "volume"
    )
    frame = pd.DataFrame(rows)
    returns = []
    if not frame.empty:
        frame["close"] = pd.to_numeric(frame["close"])
        frame["volume"] = pd.to_numeric(frame["volume"])
        for _, prices in frame.groupby("instrument_id"):
            prices = prices.sort_values("timestamp")
            momentum = prices.close.pct_change(20)
            relative_volume = prices.volume / prices.volume.rolling(20).median()
            future_return = prices.close.shift(-holding_days) / prices.close - 1 - fee_rate
            mask = (momentum > 0.05) & (relative_volume > 1.2)
            returns.extend(future_return[mask].dropna().tolist())
    if not returns:
        report = BacktestReport(0, 0, 0, 0, 0)
    else:
        series = pd.Series(returns, dtype=float)
        gains, losses = series[series > 0].sum(), abs(series[series < 0].sum())
        equity = (1 + series).cumprod()
        drawdown = equity / equity.cummax() - 1
        report = BacktestReport(
            len(series),
            round(float((series > 0).mean()), 4),
            round(float(gains / losses), 3) if losses else 99.0,
            round(float(series.mean()), 5),
            round(float(drawdown.min()), 4),
        )
    curve = (
        [round(float(value), 5) for value in equity.iloc[:: max(1, len(equity) // 200)]]
        if returns
        else []
    )
    PerformanceSnapshot.objects.create(
        strategy="momentum_20d_rvol",
        trades=report.trades,
        win_rate=report.win_rate,
        profit_factor=report.profit_factor,
        expectancy=report.expectancy,
        max_drawdown=report.max_drawdown,
        equity_curve=curve,
        parameters={
            "holding_days": holding_days,
            "fee_rate": fee_rate,
            "entry": "momentum_20d > 5% and relative_volume > 1.2",
        },
    )
    return report
