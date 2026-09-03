from django.core.management.base import BaseCommand

from trading.universe import sync_idx_universe


class Command(BaseCommand):
    help = "Discover the complete share universe from KSEI"

    def handle(self, *args, **options):
        count, observed_at = sync_idx_universe()
        self.stdout.write(self.style.SUCCESS(f"Loaded {count} instruments at {observed_at}"))
