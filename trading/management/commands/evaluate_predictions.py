from django.core.management.base import BaseCommand

from trading.evaluation import evaluate_predictions


class Command(BaseCommand):
    help = "Evaluate prior predictions against the next available daily close"

    def handle(self, *args, **options):
        self.stdout.write(f"Evaluated {evaluate_predictions()} predictions")
