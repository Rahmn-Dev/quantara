from django.utils import timezone

from .models import Candle, PredictionRecord


def evaluate_predictions():
    evaluated = 0
    pending = PredictionRecord.objects.filter(evaluated_at__isnull=True)
    for prediction in pending:
        next_candle = (
            Candle.objects.filter(
                instrument=prediction.instrument,
                interval="1d",
                timestamp__date__gt=prediction.signal_date,
            )
            .order_by("timestamp")
            .first()
        )
        if not next_candle:
            continue
        realized_return = float(next_candle.close / prediction.reference_price - 1)
        prediction.realized_price = next_candle.close
        prediction.realized_return = realized_return
        prediction.was_correct = (
            realized_return > 0 if prediction.predicted_direction == "UP" else realized_return < 0
        )
        prediction.evaluated_at = timezone.now()
        prediction.save(
            update_fields=["realized_price", "realized_return", "was_correct", "evaluated_at"]
        )
        evaluated += 1
    return evaluated
