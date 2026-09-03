import numpy as np
import pandas as pd

from .engine import Snapshot
from .models import Candle, Instrument


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
    return Snapshot(
        symbol=instrument.symbol,
        close=float(close.iloc[-1]),
        momentum_20d=float(close.iloc[-1] / close.iloc[-21] - 1),
        relative_volume=float(volume.iloc[-1] / max(volume.tail(21).iloc[:-1].median(), 1)),
        distance_to_vwap=float(close.iloc[-1] / vwap20 - 1),
        atr_percent=float(atr_pct),
        liquidity_score=float(liquidity),
        broker_flow_score=50,
        gap_percent=float(frame.open.iloc[-1] / close.iloc[-2] - 1),
    )
