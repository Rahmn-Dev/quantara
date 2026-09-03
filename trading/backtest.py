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


def run_momentum_backtest(*, holding_days=1, buy_fee=0.0015, sell_fee=0.0025, slippage=0.001) -> BacktestReport:
    """Next-day portfolio test with costs; overlapping signals are grouped per session."""
    rows = Candle.objects.filter(interval="1d").values(
        "instrument_id", "timestamp", "open", "high", "low", "close", "volume"
    )
    frame = pd.DataFrame(rows)
    trades = []
    if not frame.empty:
        frame["close"] = pd.to_numeric(frame["close"])
        frame["volume"] = pd.to_numeric(frame["volume"])
        for instrument_id, prices in frame.groupby("instrument_id"):
            prices = prices.sort_values("timestamp")
            momentum = prices.close.pct_change(20)
            relative_volume = prices.volume / prices.volume.rolling(20).median()
            sma20 = prices.close.rolling(20).mean()
            distance = prices.close / sma20 - 1
            entry = pd.to_numeric(prices.open.shift(-1)) * (1 + slippage)
            exit_price = pd.to_numeric(prices.close.shift(-holding_days)) * (1 - slippage)
            future_return = exit_price / entry - 1 - buy_fee - sell_fee
            mask = (momentum > 0.03) & (relative_volume > 1.2) & (distance < 0.15)
            selected = pd.DataFrame({"date": prices.timestamp, "instrument": instrument_id,
                                     "score": momentum * relative_volume, "return": future_return})[mask].dropna()
            # Exclude sessions that could not reasonably be filled around IDX price limits.
            selected = selected[selected["return"].abs() < 0.25]
            trades.append(selected)
    selected = pd.concat(trades, ignore_index=True) if trades else pd.DataFrame()
    if selected.empty:
        report = BacktestReport(0, 0, 0, 0, 0)
        portfolio_returns = pd.Series(dtype=float)
    else:
        selected = selected.sort_values(["date", "score"], ascending=[True, False]).groupby("date").head(5)
        series = selected["return"].astype(float)
        portfolio_returns = selected.groupby("date")["return"].mean().sort_index()
        gains, losses = series[series > 0].sum(), abs(series[series < 0].sum())
        equity = (1 + portfolio_returns.clip(lower=-0.25, upper=0.25)).cumprod()
        drawdown = equity / equity.cummax() - 1
        report = BacktestReport(
            len(selected),
            round(float((series > 0).mean()), 4),
            round(float(gains / losses), 3) if losses else 99.0,
            round(float(series.mean()), 5),
            round(float(drawdown.min()), 4),
        )
    curve = (
        [round(float(value), 5) for value in equity.iloc[:: max(1, len(equity) // 200)]]
        if not portfolio_returns.empty
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
            "buy_fee": buy_fee, "sell_fee": sell_fee, "slippage_each_side": slippage,
            "max_positions_per_day": 5, "holding_days": holding_days,
            "entry": "next open; momentum_20d > 3%, relative_volume > 1.2, distance_sma20 < 15%",
            "price_limit_filter": "absolute modeled return below 25%",
            "survivorship_bias_free": False,
        },
    )
    return report
