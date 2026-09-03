from celery import shared_task

from .evaluation import evaluate_predictions
from .scanner import scan_market
from .services import broadcast_plans


@shared_task
def build_daily_plan():
    return scan_market().instruments_scanned


@shared_task
def validate_live_setups():
    # Production adapter refreshes 1m/5m candles before this broadcast.
    broadcast_plans()
    return "validation broadcast"


@shared_task
def score_predictions():
    return evaluate_predictions()
