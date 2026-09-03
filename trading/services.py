from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.utils import timezone

from .engine import Snapshot, create_decision
from .models import Instrument, TradePlan

DEMO_MARKET = [
    Snapshot("BBCA", 9225, 0.062, 1.65, 0.004, 0.026, 96, 68, 0.006),
    Snapshot("BMRI", 6150, 0.084, 1.82, 0.006, 0.032, 94, 74, 0.009),
    Snapshot("ANTM", 1535, 0.115, 2.10, 0.011, 0.047, 86, 80, 0.012),
    Snapshot("GOTO", 78, 0.041, 1.10, -0.005, 0.055, 82, 45, 0.026),
    Snapshot("TLKM", 3190, -0.018, 0.92, -0.008, 0.021, 95, 42, -0.004),
]


def generate_demo_plans(equity=100_000_000, daily_pnl_pct=0, regime="BULLISH"):
    trading_date = timezone.localdate()
    limits = settings.QUANT_LIMITS
    decisions = [
        create_decision(
            s,
            equity=equity,
            daily_pnl_pct=daily_pnl_pct,
            regime=regime,
            min_score=limits["min_signal_score"],
            min_rr=limits["min_risk_reward"],
            max_risk=limits["max_risk_per_trade"],
            max_daily_loss=limits["max_daily_loss"],
        )
        for s in DEMO_MARKET
    ]
    plans = []
    for d in sorted(decisions, key=lambda item: item.score, reverse=True)[:3]:
        instrument, _ = Instrument.objects.get_or_create(symbol=d.symbol)
        values = d.to_dict()
        values.pop("symbol")
        plan, _ = TradePlan.objects.update_or_create(
            instrument=instrument,
            trading_date=trading_date,
            strategy="momentum",
            defaults={
                **values,
                "commentary": "Quant score lolos lebih dulu; narasi ini tidak dapat mengubah risk veto.",
            },
        )
        plans.append(plan)
    broadcast_plans()
    return plans


def broadcast_plans():
    layer = get_channel_layer()
    async_to_sync(layer.group_send)(
        "market", {"type": "market.update", "payload": {"event": "plans.updated"}}
    )
