from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("trading", "0006_alter_tradeplan_status")]

    operations = [
        migrations.AddField(model_name="tradeplan", name="ranking_score", field=models.FloatField(default=0)),
        migrations.AddField(model_name="tradeplan", name="indicators", field=models.JSONField(default=dict)),
        migrations.AddField(model_name="tradeplan", name="scan_settings", field=models.JSONField(default=dict)),
    ]
