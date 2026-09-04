from dataclasses import asdict

from django.core.management.base import BaseCommand

from trading.backtest import run_model_backtest


class Command(BaseCommand):
    help = "Run an anchored out-of-sample audit of the selected model"

    def add_arguments(self, parser):
        parser.add_argument("--profile", choices=["NEXT_DAY", "SWING"], default="NEXT_DAY")

    def handle(self, *args, **options):
        self.stdout.write(str(asdict(run_model_backtest(profile=options["profile"]))))
