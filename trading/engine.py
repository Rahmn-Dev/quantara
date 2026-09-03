from dataclasses import asdict, dataclass
from math import isfinite


@dataclass(frozen=True)
class Snapshot:
    symbol: str
    close: float
    momentum_20d: float
    relative_volume: float
    distance_to_vwap: float
    atr_percent: float
    liquidity_score: float
    broker_flow_score: float = 50.0
    gap_percent: float = 0.0
    momentum_5d: float = 0.0
    momentum_60d: float = 0.0
    momentum_120d: float = 0.0
    volatility_20d: float = 0.0
    distance_to_sma20: float = 0.0
    rsi_14: float = 50.0
    bollinger_position: float = 0.5
    consecutive_green_days: int = 0
    volume_climax: float = 1.0
    median_turnover_20d: float = 0.0


@dataclass(frozen=True)
class Decision:
    symbol: str
    score: float
    confidence: float
    entry_low: float
    entry_high: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    position_size: int
    status: str
    checks: dict
    veto_reasons: list[str]

    def to_dict(self):
        return asdict(self)


def clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


def quant_score(s: Snapshot) -> float:
    """Transparent score; every input is measurable and independently testable."""
    momentum = clamp(50 + s.momentum_5d * 140 + s.momentum_20d * 130 + s.momentum_60d * 45)
    volume = clamp((s.relative_volume - 0.5) * 50)
    vwap = clamp(70 + s.distance_to_vwap * 500)
    volatility = clamp(100 - abs(s.atr_percent - 0.035) * 1800)
    base = (
        0.31 * momentum
        + 0.24 * volume
        + 0.17 * vwap
        + 0.13 * volatility
        + 0.15 * s.liquidity_score
    )
    # Prevent trend-following from becoming blind performance chasing.
    penalty = 0.0
    penalty += max(0.0, s.rsi_14 - 70) * 0.65
    penalty += max(0.0, s.distance_to_sma20 - 0.09) * 150
    penalty += max(0.0, s.bollinger_position - 1.05) * 18
    penalty += max(0, s.consecutive_green_days - 4) * 1.75
    penalty += max(0.0, s.volume_climax - 3.0) * 2.0
    return round(clamp(base - min(penalty, 28)), 2)


def create_decision(
    s: Snapshot,
    *,
    equity: float,
    daily_pnl_pct: float,
    regime: str,
    min_score=65,
    min_rr=1.5,
    max_risk=0.01,
    max_daily_loss=0.02,
) -> Decision:
    if not all(isfinite(v) for v in asdict(s).values() if isinstance(v, float)) or s.close <= 0:
        raise ValueError("Invalid market snapshot")
    score = quant_score(s)
    entry_low, entry_high = s.close * 0.995, s.close * 1.005
    stop = s.close * (1 - max(0.018, min(s.atr_percent, 0.06)))
    target = s.close * (1 + max(0.03, s.atr_percent * 1.8))
    rr = (target - s.close) / (s.close - stop)
    risk_per_share = s.close - stop
    size = max(0, int((equity * max_risk) / risk_per_share) // 100 * 100)
    checks = {
        "signal": score >= min_score,
        "risk_reward": rr >= min_rr,
        "daily_loss": daily_pnl_pct > -max_daily_loss,
        "gap": abs(s.gap_percent) < 0.02,
        "volume": s.relative_volume >= 1.2,
        "vwap": s.distance_to_vwap >= 0,
        "regime": regime != "HIGH_RISK",
        "liquidity": s.liquidity_score >= 55,
        "not_overextended": (
            s.rsi_14 <= 78
            and s.distance_to_sma20 <= 0.15
            and s.consecutive_green_days <= 6
            and s.volume_climax <= 5
        ),
    }
    reasons = [name.replace("_", " ").title() for name, passed in checks.items() if not passed]
    ready = all(checks.values()) and size > 0
    confidence = round(min(0.95, max(0.05, score / 100 * (sum(checks.values()) / len(checks)))), 3)
    return Decision(
        s.symbol,
        score,
        confidence,
        round(entry_low, 2),
        round(entry_high, 2),
        round(stop, 2),
        round(target, 2),
        round(rr, 2),
        size,
        "READY" if ready else "WAIT",
        checks,
        reasons,
    )
