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

FEATURES = ["ret_5", "ret_20", "rvol", "volatility", "sma20_distance", "range_pct"]
ARTIFACT_DIR = Path(settings.BASE_DIR) / "artifacts"
ARTIFACT_PATH = ARTIFACT_DIR / "champion.joblib"


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


def training_frame():
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
        frame["rvol"] = frame.volume / frame.volume.rolling(20).median()
        frame["volatility"] = frame.close.pct_change().rolling(20).std()
        frame["sma20_distance"] = frame.close / frame.close.rolling(20).mean() - 1
        frame["range_pct"] = (frame.high - frame.low) / frame.close
        frame["future_return"] = frame.close.shift(-5) / frame.close - 1 - 0.003
        frame["target"] = (frame.future_return > 0.01).astype(int)
        frame["instrument_id"] = instrument_id
        samples.append(frame.dropna(subset=FEATURES + ["future_return"]))
    return pd.concat(samples).sort_values("timestamp").reset_index(drop=True)


def train_champion():
    frame = training_frame()
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
        prediction = probability >= settings.QUANT_LIMITS["min_ml_probability"]
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
    joblib.dump({"model": champion, "features": FEATURES}, ARTIFACT_PATH)
    load_champion.cache_clear()
    mean_auc = float(np.mean([fold["auc"] for fold in fold_metrics]))
    return ModelRun.objects.create(
        samples=len(frame),
        features=FEATURES,
        metrics={
            "walk_forward": fold_metrics,
            "mean_auc": round(mean_auc, 4),
            "positive_rate": round(float(frame.target.mean()), 4),
            "calibration": "sigmoid_temporal_holdout",
            "calibration_start": champion_calibration_start,
            "mean_brier": round(float(np.mean([fold["brier"] for fold in fold_metrics])), 4),
            "mean_calibration_error": round(
                float(np.mean([fold["calibration_error"] for fold in fold_metrics])), 4
            ),
        },
        artifact_path=str(ARTIFACT_PATH),
    )


@lru_cache(maxsize=1)
def load_champion():
    return joblib.load(ARTIFACT_PATH)


def predict_probability(snapshot):
    if not ARTIFACT_PATH.exists():
        return None
    bundle = load_champion()
    # Map the live snapshot into the subset measurable at decision time.
    vector = pd.DataFrame(
        [
            {
                "ret_5": snapshot.momentum_20d / 4,
                "ret_20": snapshot.momentum_20d,
                "rvol": snapshot.relative_volume,
                "volatility": snapshot.atr_percent / 2,
                "sma20_distance": snapshot.distance_to_vwap,
                "range_pct": snapshot.atr_percent,
            }
        ],
        columns=bundle["features"],
    )
    return float(bundle["model"].predict_proba(vector)[0, 1])
