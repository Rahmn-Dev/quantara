import numpy as np
import pandas as pd

from .engine import Snapshot
from .models import BrokerFlow, Candle, ForeignFlow, FundamentalSnapshot, Instrument


def get_broker_flow_score(instrument: Instrument) -> float:
    """
    Returns the institutional_score (0-100) from the most recent BrokerFlow
    record for this instrument. Falls back to neutral 50 if no data.
    """
    bf = get_broker_flow_details(instrument)
    return bf.institutional_score if bf else 50.0

def get_broker_flow_details(instrument: Instrument):
    """Returns the most recent BrokerFlow object for this instrument."""
    return (
        BrokerFlow.objects
        .filter(instrument=instrument, raw_available=True)
        .order_by("-trading_date")
        .first()
    )


def get_foreign_flow_signal(instrument: Instrument) -> str:
    """
    Returns the most recent ForeignFlow signal: ACCUMULATE / DISTRIBUTE / NEUTRAL.
    """
    ff = (
        ForeignFlow.objects
        .filter(instrument=instrument)
        .order_by("-trading_date")
        .first()
    )
    return ff.signal if ff else "NEUTRAL"


def get_fundamental(instrument: Instrument) -> dict:
    """
    Returns the most recent FundamentalSnapshot as a dict.
    Returns empty dict if no data is available yet.
    """
    fs = (
        FundamentalSnapshot.objects
        .filter(instrument=instrument)
        .order_by("-period_year", "-period_quarter")
        .first()
    )
    if not fs:
        return {}
    return {
        "per": fs.per,
        "pbv": fs.pbv,
        "roe": fs.roe,
        "der": fs.der,
        "eps": fs.eps,
        "revenue_growth": fs.revenue_growth,
    }


def candle_frame(instrument: Instrument, interval="1d") -> pd.DataFrame:
    rows = Candle.objects.filter(instrument=instrument, interval=interval).values(
        "timestamp", "open", "high", "low", "close", "volume"
    )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column])
    return frame.sort_values("timestamp").set_index("timestamp")


def build_snapshot(instrument: Instrument) -> Snapshot:
    frame = candle_frame(instrument)
    if len(frame) < 30:
        raise ValueError(f"{instrument.symbol}: need at least 30 candles")
    close = frame["close"]
    volume = frame["volume"]
    true_range = pd.concat(
        [
            (frame.high - frame.low),
            (frame.high - close.shift()).abs(),
            (frame.low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_pct = true_range.rolling(14).mean().iloc[-1] / close.iloc[-1]
    turnover = close * volume
    liquidity = np.clip(35 + np.log10(max(turnover.tail(20).median(), 1)) * 7, 0, 100)
    typical = (frame.high + frame.low + close) / 3
    vwap20 = (typical.tail(20) * volume.tail(20)).sum() / max(volume.tail(20).sum(), 1)
    if not np.isfinite(vwap20) or vwap20 <= 0:
        raise ValueError(f"{instrument.symbol}: invalid VWAP from zero-volume history")
    returns = close.pct_change()
    delta = close.diff()
    avg_gain = delta.clip(lower=0).rolling(14).mean().iloc[-1]
    avg_loss = -delta.clip(upper=0).rolling(14).mean().iloc[-1]
    rsi14 = 100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    sma20 = close.rolling(20).mean().iloc[-1]
    std20 = close.rolling(20).std().iloc[-1]
    upper, lower = sma20 + 2 * std20, sma20 - 2 * std20
    consecutive_green = 0
    for value in (close > frame.open).iloc[::-1]:
        if not value:
            break
        consecutive_green += 1
    rvol = float(volume.iloc[-1] / max(volume.tail(21).iloc[:-1].median(), 1))
    return Snapshot(
        symbol=instrument.symbol,
        close=float(close.iloc[-1]),
        momentum_20d=float(close.iloc[-1] / close.iloc[-21] - 1),
        relative_volume=rvol,
        distance_to_vwap=float(close.iloc[-1] / vwap20 - 1),
        atr_percent=float(atr_pct),
        liquidity_score=float(liquidity),
        broker_flow_score=get_broker_flow_score(instrument),  # Real IDX data (Phase 1)
        gap_percent=float(frame.open.iloc[-1] / close.iloc[-2] - 1),
        momentum_5d=float(close.iloc[-1] / close.iloc[-6] - 1),
        momentum_60d=float(close.iloc[-1] / close.iloc[-61] - 1) if len(close) >= 61 else 0.0,
        momentum_120d=float(close.iloc[-1] / close.iloc[-121] - 1) if len(close) >= 121 else 0.0,
        volatility_20d=float(returns.rolling(20).std().iloc[-1]),
        distance_to_sma20=float(close.iloc[-1] / sma20 - 1),
        rsi_14=float(rsi14),
        bollinger_position=float((close.iloc[-1] - lower) / max(upper - lower, 1e-9)),
        consecutive_green_days=consecutive_green,
        volume_climax=rvol,
        median_turnover_20d=float(turnover.tail(20).median()),
    )
