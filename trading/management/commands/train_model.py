from django.core.management.base import BaseCommand

from trading.ml import train_champion


class Command(BaseCommand):
    help = "Train and walk-forward validate the local ML champion model"

    def add_arguments(self, parser):
        parser.add_argument("--profile", choices=["NEXT_DAY", "SWING", "ALL"], default="ALL")

    def handle(self, *args, **options):
        profiles = ["NEXT_DAY", "SWING"] if options["profile"] == "ALL" else [options["profile"]]
        for profile in profiles:
            run = train_champion(profile)
            self.stdout.write(f"profile={profile} model={run.name} samples={run.samples} metrics={run.metrics}")
