from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("trading", "0009_decision_windows")]

    operations = [
        migrations.CreateModel(
            name="DemoOrder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("side", models.CharField(default="BUY", max_length=4)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("FILLED", "Filled"), ("REJECTED", "Rejected"), ("EXPIRED", "Expired")], default="PENDING", max_length=10)),
                ("requested_lots", models.PositiveIntegerField()),
                ("filled_lots", models.PositiveIntegerField(default=0)),
                ("submitted_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("filled_at", models.DateTimeField(blank=True, null=True)),
                ("reference_price", models.DecimalField(decimal_places=4, max_digits=16)),
                ("fill_price", models.DecimalField(blank=True, decimal_places=4, max_digits=16, null=True)),
                ("fee", models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ("slippage_percent", models.FloatField(default=0)),
                ("reason", models.CharField(blank=True, max_length=180)),
                ("metadata", models.JSONField(default=dict)),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="orders", to="trading.demoaccount")),
                ("instrument", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="trading.instrument")),
                ("position", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="trading.demoposition")),
                ("trade_plan", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to="trading.tradeplan")),
            ],
            options={"ordering": ["-submitted_at"]},
        ),
    ]
