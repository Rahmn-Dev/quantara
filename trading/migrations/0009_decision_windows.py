from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("trading", "0008_demoaccount_demoposition")]
    operations = [
        migrations.AddField(model_name="scanrun", name="decision_window", field=models.CharField(default="LEGACY", max_length=16)),
        migrations.AddField(model_name="tradeplan", name="decision_window", field=models.CharField(db_index=True, default="LEGACY", max_length=16)),
        migrations.AddField(model_name="predictionrecord", name="decision_window", field=models.CharField(db_index=True, default="LEGACY", max_length=16)),
        migrations.RemoveConstraint(model_name="tradeplan", name="unique_daily_strategy"),
        migrations.AddConstraint(model_name="tradeplan", constraint=models.UniqueConstraint(fields=("instrument", "trading_date", "strategy", "decision_window"), name="unique_daily_strategy_window")),
        migrations.RemoveConstraint(model_name="predictionrecord", name="unique_prediction_record"),
        migrations.AddConstraint(model_name="predictionrecord", constraint=models.UniqueConstraint(fields=("instrument", "signal_date", "model_name", "horizon_days", "decision_window"), name="unique_prediction_window")),
    ]
