from dataclasses import dataclass
from datetime import timedelta

import pandas as pd
import yfinance as yf
from django.utils import timezone

from .models import Candle, Instrument


@dataclass
class SyncResult:
    symbol: str
    rows: int
    latest: object | None


class YahooMarketData:
    """Personal-research adapter. Quotes may be delayed; never label them exchange realtime."""

    source = "yahoo"

    def fetch(self, symbol: str, *, period="1y", interval="1d") -> pd.DataFrame:
        ticker = symbol if symbol.endswith(".JK") or symbol.startswith("^") else f"{symbol}.JK"
        frame = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
            threads=False,
            timeout=20,
            multi_level_index=False,
        )
        if frame.empty:
            raise ValueError(f"No market data returned for {ticker}")
        return frame.dropna(subset=["Open", "High", "Low", "Close"])

    def sync(self, instrument: Instrument, *, period="1y", interval="1d") -> SyncResult:
        frame = self.fetch(instrument.symbol, period=period, interval=interval)
        rows = 0
        latest = None
        for index, row in frame.iterrows():
            stamp = index.to_pydatetime()
            if timezone.is_naive(stamp):
                stamp = timezone.make_aware(stamp)
            latest = max(latest, stamp) if latest else stamp
            Candle.objects.update_or_create(
                instrument=instrument,
                timestamp=stamp,
                interval=interval,
                defaults={
                    "open": row["Open"],
                    "high": row["High"],
                    "low": row["Low"],
                    "close": row["Close"],
                    "volume": int(row.get("Volume", 0)),
                    "source": self.source,
                },
            )
            rows += 1
        return SyncResult(instrument.symbol, rows, latest)


def is_stale(timestamp, interval="1d"):
    limit = timedelta(days=4) if interval == "1d" else timedelta(minutes=20)
    return not timestamp or timezone.now() - timestamp > limit
