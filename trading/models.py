from django.db import models


class Instrument(models.Model):
    symbol = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=160, blank=True)
    sector = models.CharField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.symbol


class Candle(models.Model):
    class Interval(models.TextChoices):
        DAY = "1d", "Daily"
        FIVE_MINUTES = "5m", "Five minutes"

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="candles")
    timestamp = models.DateTimeField()
    interval = models.CharField(max_length=4, choices=Interval.choices, default=Interval.DAY)
    open = models.DecimalField(max_digits=16, decimal_places=4)
    high = models.DecimalField(max_digits=16, decimal_places=4)
    low = models.DecimalField(max_digits=16, decimal_places=4)
    close = models.DecimalField(max_digits=16, decimal_places=4)
    volume = models.BigIntegerField(default=0)
    source = models.CharField(max_length=32, default="yahoo")

    class Meta:
        ordering = ["timestamp"]
        constraints = [
            models.UniqueConstraint(
                fields=["instrument", "timestamp", "interval"], name="unique_candle"
            )
        ]


class ScanRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "RUNNING"
        COMPLETE = "COMPLETE"
        FAILED = "FAILED"

    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RUNNING)
    source = models.CharField(max_length=32, default="yahoo")
    interval = models.CharField(max_length=4, default="1d")
    instruments_scanned = models.PositiveIntegerField(default=0)
    freshest_candle_at = models.DateTimeField(null=True, blank=True)
    errors = models.JSONField(default=list)
    decision_window = models.CharField(max_length=16, default="LEGACY")


class ModelRun(models.Model):
    trained_at = models.DateTimeField(auto_now_add=True)
    name = models.CharField(max_length=80, default="hist_gradient_boosting")
    status = models.CharField(max_length=16, default="TRAINED")
    samples = models.PositiveIntegerField(default=0)
    features = models.JSONField(default=list)
    metrics = models.JSONField(default=dict)
    artifact_path = models.CharField(max_length=255)


class LiveQuote(models.Model):
    instrument = models.OneToOneField(
        Instrument, on_delete=models.CASCADE, related_name="live_quote"
    )
    price = models.DecimalField(max_digits=16, decimal_places=4)
    change_percent = models.FloatField(default=0)
    volume = models.BigIntegerField(default=0)
    market_time = models.DateTimeField()
    received_at = models.DateTimeField(auto_now=True)
    source = models.CharField(max_length=32, default="yahoo-stream")


class PredictionRecord(models.Model):
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE)
    trade_plan = models.ForeignKey("TradePlan", on_delete=models.SET_NULL, null=True, blank=True)
    predicted_at = models.DateTimeField(auto_now_add=True)
    signal_date = models.DateField(db_index=True)
    horizon_days = models.PositiveSmallIntegerField(default=1)
    model_name = models.CharField(max_length=80)
    model_probability = models.FloatField()
    quant_score = models.FloatField()
    decision = models.CharField(max_length=16)
    reference_price = models.DecimalField(max_digits=16, decimal_places=4)
    predicted_direction = models.CharField(max_length=8, default="UP")
    realized_price = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True)
    realized_return = models.FloatField(null=True, blank=True)
    was_correct = models.BooleanField(null=True, blank=True)
    evaluated_at = models.DateTimeField(null=True, blank=True)
    evidence = models.JSONField(default=dict)
    decision_window = models.CharField(max_length=16, default="LEGACY", db_index=True)

    class Meta:
        ordering = ["-predicted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["instrument", "signal_date", "model_name", "horizon_days", "decision_window"],
                name="unique_prediction_window",
            )
        ]


class MarketRegime(models.Model):
    class State(models.TextChoices):
        BULLISH = "BULLISH"
        NEUTRAL = "NEUTRAL"
        HIGH_RISK = "HIGH_RISK"

    observed_at = models.DateTimeField()
    state = models.CharField(max_length=16, choices=State.choices)
    score = models.FloatField()
    notes = models.JSONField(default=list)


class TradePlan(models.Model):
    class Status(models.TextChoices):
        WAIT = "WAIT"
        WATCH = "WATCH"
        SETUP = "SETUP"
        REJECT = "REJECT"
        READY = "READY"
        INVALIDATED = "INVALIDATED"
        CLOSED = "CLOSED"

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE)
    trading_date = models.DateField(db_index=True)
    strategy = models.CharField(max_length=40, default="momentum")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.WAIT)
    score = models.FloatField()
    confidence = models.FloatField()
    entry_low = models.DecimalField(max_digits=14, decimal_places=2)
    entry_high = models.DecimalField(max_digits=14, decimal_places=2)
    stop_loss = models.DecimalField(max_digits=14, decimal_places=2)
    take_profit = models.DecimalField(max_digits=14, decimal_places=2)
    risk_reward = models.FloatField()
    position_size = models.PositiveIntegerField(default=0)
    ranking_score = models.FloatField(default=0)
    indicators = models.JSONField(default=dict)
    scan_settings = models.JSONField(default=dict)
    checks = models.JSONField(default=dict)
    veto_reasons = models.JSONField(default=list)
    commentary = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    decision_window = models.CharField(max_length=16, default="LEGACY", db_index=True)

    class Meta:
        ordering = ["-trading_date", "-score"]
        constraints = [
            models.UniqueConstraint(fields=["instrument", "trading_date", "strategy", "decision_window"], name="unique_daily_strategy_window")
        ]


class PerformanceSnapshot(models.Model):
    strategy = models.CharField(max_length=40)
    computed_at = models.DateTimeField(auto_now_add=True)
    trades = models.PositiveIntegerField(default=0)
    win_rate = models.FloatField(default=0)
    profit_factor = models.FloatField(default=0)
    expectancy = models.FloatField(default=0)
    max_drawdown = models.FloatField(default=0)
    equity_curve = models.JSONField(default=list)
    parameters = models.JSONField(default=dict)


class DemoAccount(models.Model):
    name = models.CharField(max_length=80, default="Paper Trading")
    starting_cash = models.DecimalField(max_digits=18, decimal_places=2, default=100_000_000)
    cash = models.DecimalField(max_digits=18, decimal_places=2, default=100_000_000)
    realized_pnl = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class DemoPosition(models.Model):
    account = models.ForeignKey(DemoAccount, on_delete=models.CASCADE, related_name="positions")
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    trade_plan = models.ForeignKey(TradePlan, on_delete=models.SET_NULL, null=True)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    shares = models.PositiveIntegerField()
    entry_price = models.DecimalField(max_digits=16, decimal_places=4)
    exit_price = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True)
    entry_fee = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    exit_fee = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    realized_pnl = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=8, default="OPEN")

    class Meta:
        ordering = ["-opened_at"]
