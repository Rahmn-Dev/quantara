from django.contrib import admin

from .models import (
    Candle,
    Instrument,
    MarketRegime,
    PerformanceSnapshot,
    PredictionRecord,
    ScanRun,
    TradePlan,
)

admin.site.register(
    [Instrument, Candle, ScanRun, MarketRegime, PerformanceSnapshot, TradePlan, PredictionRecord]
)
