from django.core.management.base import BaseCommand

from trading.ml import train_champion


class Command(BaseCommand):
    help = "Train and walk-forward validate the local ML champion model"

    def handle(self, *args, **options):
        run = train_champion()
        self.stdout.write(f"model={run.name} samples={run.samples} metrics={run.metrics}")
