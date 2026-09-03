from rest_framework import serializers

from .models import TradePlan


class TradePlanSerializer(serializers.ModelSerializer):
    symbol = serializers.CharField(source="instrument.symbol", read_only=True)

    class Meta:
        model = TradePlan
        fields = [
            "id",
            "symbol",
            "trading_date",
            "strategy",
            "decision_window",
            "status",
            "score",
            "confidence",
            "entry_low",
            "entry_high",
            "stop_loss",
            "take_profit",
            "risk_reward",
            "position_size",
            "ranking_score",
            "indicators",
            "scan_settings",
            "checks",
            "veto_reasons",
            "commentary",
            "updated_at",
        ]
