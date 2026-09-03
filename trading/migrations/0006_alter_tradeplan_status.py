from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("trading", "0005_performancesnapshot_equity_curve_and_more")]

    operations = [
        migrations.AlterField(
            model_name="tradeplan",
            name="status",
            field=models.CharField(
                choices=[
                    ("WAIT", "Wait"),
                    ("WATCH", "Watch"),
                    ("SETUP", "Setup"),
                    ("REJECT", "Reject"),
                    ("READY", "Ready"),
                    ("INVALIDATED", "Invalidated"),
                    ("CLOSED", "Closed"),
                ],
                default="WAIT",
                max_length=16,
            ),
        ),
    ]
