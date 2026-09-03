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
    momentum = clamp(50 + s.momentum_20d * 250)
    volume = clamp((s.relative_volume - 0.5) * 50)
    vwap = clamp(70 + s.distance_to_vwap * 500)
    volatility = clamp(100 - abs(s.atr_percent - 0.035) * 1800)
    return round(
        0.28 * momentum
        + 0.22 * volume
        + 0.15 * vwap
        + 0.12 * volatility
        + 0.13 * s.liquidity_score
        + 0.10 * s.broker_flow_score,
        2,
    )


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
