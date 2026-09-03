from dataclasses import asdict

from django.core.management.base import BaseCommand

from trading.backtest import run_momentum_backtest


class Command(BaseCommand):
    help = "Run a leakage-safe momentum backtest over locally cached candles"

    def handle(self, *args, **options):
        self.stdout.write(str(asdict(run_momentum_backtest())))
