from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("trading", "0007_tradeplan_evidence")]
    operations = [
        migrations.CreateModel(name="DemoAccount", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(default="Paper Trading", max_length=80)),
            ("starting_cash", models.DecimalField(decimal_places=2, default=100000000, max_digits=18)),
            ("cash", models.DecimalField(decimal_places=2, default=100000000, max_digits=18)),
            ("realized_pnl", models.DecimalField(decimal_places=2, default=0, max_digits=18)),
            ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
        ]),
        migrations.CreateModel(name="DemoPosition", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("opened_at", models.DateTimeField(auto_now_add=True)), ("closed_at", models.DateTimeField(blank=True, null=True)),
            ("shares", models.PositiveIntegerField()), ("entry_price", models.DecimalField(decimal_places=4, max_digits=16)),
            ("exit_price", models.DecimalField(blank=True, decimal_places=4, max_digits=16, null=True)),
            ("entry_fee", models.DecimalField(decimal_places=2, default=0, max_digits=16)),
            ("exit_fee", models.DecimalField(decimal_places=2, default=0, max_digits=16)),
            ("realized_pnl", models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
            ("status", models.CharField(default="OPEN", max_length=8)),
            ("account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="positions", to="trading.demoaccount")),
            ("instrument", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="trading.instrument")),
            ("trade_plan", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to="trading.tradeplan")),
        ], options={"ordering": ["-opened_at"]}),
    ]
