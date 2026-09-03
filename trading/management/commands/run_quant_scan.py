from django.core.management.base import BaseCommand

from trading.scanner import scan_market


class Command(BaseCommand):
    help = "Fetch current daily candles and build ranked IDX trade plans"

    def add_arguments(self, parser):
        parser.add_argument("--equity", type=float, default=100_000_000)
        parser.add_argument("--no-sync", action="store_true")

    def handle(self, *args, **options):
        run = scan_market(equity=options["equity"], sync=not options["no_sync"])
        self.stdout.write(
            f"{run.status}: {run.instruments_scanned} scanned, {len(run.errors)} errors"
        )
