from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from django.conf import settings
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, precision_score, roc_auc_score

from .models import Candle, ModelRun

FEATURES = ["ret_5", "ret_20", "ret_60", "ret_120", "rvol", "volatility", "sma20_distance", "range_pct", "rsi_14", "bollinger_position", "consecutive_green"]
ARTIFACT_DIR = Path(settings.BASE_DIR) / "artifacts"
LEGACY_ARTIFACT_PATH = ARTIFACT_DIR / "champion.joblib"


def artifact_path(profile="NEXT_DAY"):
    from .strategy_profiles import get_profile
    path = ARTIFACT_DIR / get_profile(profile)["artifact"]
    if profile.upper() == "NEXT_DAY" and not path.exists() and LEGACY_ARTIFACT_PATH.exists():
        return LEGACY_ARTIFACT_PATH
    return path


def _base_model(max_iter=150):
    return HistGradientBoostingClassifier(
        max_iter=max_iter,
        max_depth=4,
        learning_rate=0.05,
        l2_regularization=1.0,
        random_state=42,
    )


def _fit_time_calibrated(frame, *, max_iter=150):
    """Fit on the older 80%, sigmoid-calibrate on the newest 20%."""
    dates = frame.timestamp.drop_duplicates().sort_values()
    calibration_start = dates.iloc[max(1, int(len(dates) * 0.80))]
    fit_frame = frame[frame.timestamp < calibration_start]
    calibration_frame = frame[frame.timestamp >= calibration_start]
    model = _base_model(max_iter=max_iter)
    model.fit(fit_frame[FEATURES], fit_frame.target)
    calibrated = CalibratedClassifierCV(FrozenEstimator(model), method="sigmoid")
    calibrated.fit(calibration_frame[FEATURES], calibration_frame.target)
    return calibrated, str(calibration_start)


def _expected_calibration_error(target, probability, bins=10):
    target = np.asarray(target)
    probability = np.asarray(probability)
    edges = np.linspace(0, 1, bins + 1)
    score = 0.0
    for lower, upper in zip(edges[:-1], edges[1:]):
        mask = (probability >= lower) & (probability < upper if upper < 1 else probability <= upper)
        if mask.any():
            score += mask.mean() * abs(probability[mask].mean() - target[mask].mean())
    return float(score)


def training_frame(horizon_days=1):
    rows = Candle.objects.filter(interval="1d").values(
        "instrument_id", "timestamp", "open", "high", "low", "close", "volume"
    )
    raw = pd.DataFrame(rows)
    samples = []
    if raw.empty:
        return pd.DataFrame()
    for instrument_id, frame in raw.groupby("instrument_id"):
        frame = frame.sort_values("timestamp").copy()
        for column in ["open", "high", "low", "close", "volume"]:
            frame[column] = pd.to_numeric(frame[column])
        frame["ret_5"] = frame.close.pct_change(5)
        frame["ret_20"] = frame.close.pct_change(20)
        frame["ret_60"] = frame.close.pct_change(60)
        frame["ret_120"] = frame.close.pct_change(120)
        frame["rvol"] = frame.volume / frame.volume.rolling(20).median()
        frame["volatility"] = frame.close.pct_change().rolling(20).std()
        frame["sma20_distance"] = frame.close / frame.close.rolling(20).mean() - 1
        frame["range_pct"] = (frame.high - frame.low) / frame.close
        delta = frame.close.diff()
        avg_gain = delta.clip(lower=0).rolling(14).mean()
        avg_loss = -delta.clip(upper=0).rolling(14).mean()
        frame["rsi_14"] = 100 - 100 / (1 + avg_gain / avg_loss.replace(0, 1e-9))
        sma20 = frame.close.rolling(20).mean()
        std20 = frame.close.rolling(20).std()
        frame["bollinger_position"] = (frame.close - (sma20 - 2 * std20)) / (4 * std20).replace(0, 1e-9)
        green = (frame.close > frame.open).astype(int)
        frame["consecutive_green"] = green.groupby((green == 0).cumsum()).cumsum()
        # NEXT DAY target: next close must clear estimated round-trip friction.
        frame["future_return"] = frame.close.shift(-horizon_days) / frame.close - 1 - 0.0045
        frame["target"] = (frame.future_return > 0).astype(int)
        frame["instrument_id"] = instrument_id
        samples.append(frame.dropna(subset=FEATURES + ["future_return"]))
    return pd.concat(samples).sort_values("timestamp").reset_index(drop=True)


def train_champion(profile="NEXT_DAY"):
    from .strategy_profiles import get_profile
    profile_name = profile.upper()
    config = get_profile(profile_name)
    if config["horizon_days"] < 1:
        raise ValueError("SCALP requires a dedicated intraday dataset; daily candles are intentionally rejected")
    frame = training_frame(config["horizon_days"])
    if len(frame) < 500:
        raise ValueError("At least 500 leakage-safe samples are required")
    split_dates = frame.timestamp.drop_duplicates().sort_values()
    fold_starts = [0.60, 0.70, 0.80]
    fold_metrics = []
    for fraction in fold_starts:
        split = split_dates.iloc[int(len(split_dates) * fraction)]
        train, test = frame[frame.timestamp < split], frame[frame.timestamp >= split]
        model, calibration_start = _fit_time_calibrated(train)
        probability = model.predict_proba(test[FEATURES])[:, 1]
        prediction = probability >= config["min_probability"]
        fold_metrics.append(
            {
                "split": str(split),
                "samples": len(test),
                "auc": round(float(roc_auc_score(test.target, probability)), 4),
                "brier": round(float(brier_score_loss(test.target, probability)), 4),
                "calibration_error": round(_expected_calibration_error(test.target, probability), 4),
                "log_loss": round(float(log_loss(test.target, probability)), 4),
                "calibration_start": calibration_start,
                "accuracy": round(float(accuracy_score(test.target, prediction)), 4),
                "precision": round(
                    float(precision_score(test.target, prediction, zero_division=0)), 4
                ),
            }
        )
    champion, champion_calibration_start = _fit_time_calibrated(frame, max_iter=200)
    ARTIFACT_DIR.mkdir(exist_ok=True)
    target_path = ARTIFACT_DIR / config["artifact"]
    joblib.dump({"model": champion, "features": FEATURES, "profile": profile_name, "horizon_days": config["horizon_days"]}, target_path)
    load_champion.cache_clear()
    mean_auc = float(np.mean([fold["auc"] for fold in fold_metrics]))
    return ModelRun.objects.create(
        name=f"hist_gradient_boosting_{profile_name.lower()}", samples=len(frame),
        features=FEATURES,
        metrics={
            "walk_forward": fold_metrics,
            "mean_auc": round(mean_auc, 4),
            "positive_rate": round(float(frame.target.mean()), 4),
            "profile": profile_name,
            "target_horizon_days": config["horizon_days"],
            "target_definition": f"close_t_plus_{config['horizon_days']}_return_after_0.45pct_friction_positive",
            "calibration": "sigmoid_temporal_holdout",
            "calibration_start": champion_calibration_start,
            "mean_brier": round(float(np.mean([fold["brier"] for fold in fold_metrics])), 4),
            "mean_calibration_error": round(
                float(np.mean([fold["calibration_error"] for fold in fold_metrics])), 4
            ),
        },
        artifact_path=str(target_path),
    )


@lru_cache(maxsize=4)
def load_champion(profile="NEXT_DAY"):
    return joblib.load(artifact_path(profile))


def predict_probability(snapshot, profile="NEXT_DAY"):
    if not artifact_path(profile).exists():
        return None
    bundle = load_champion(profile.upper())
    # Map the live snapshot into the subset measurable at decision time.
    vector = pd.DataFrame(
        [
            {
                "ret_5": snapshot.momentum_5d,
                "ret_20": snapshot.momentum_20d,
                "ret_60": snapshot.momentum_60d,
                "ret_120": snapshot.momentum_120d,
                "rvol": snapshot.relative_volume,
                "volatility": snapshot.volatility_20d,
                "sma20_distance": snapshot.distance_to_sma20,
                "range_pct": snapshot.atr_percent,
                "rsi_14": snapshot.rsi_14,
                "bollinger_position": snapshot.bollinger_position,
                "consecutive_green": snapshot.consecutive_green_days,
            }
        ],
        columns=bundle["features"],
    )
    return float(bundle["model"].predict_proba(vector)[0, 1])
