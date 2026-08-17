from django.core.management.base import BaseCommand
from arcade.models import ArcadeAttempt
from arcade.services import get_arcade_today


class Command(BaseCommand):
    help = "Flips in_progress arcade attempts from past dates to abandoned."

    def handle(self, *args, **options):
        today = get_arcade_today()
        stale_qs = ArcadeAttempt.objects.filter(
            status=ArcadeAttempt.STATUS_IN_PROGRESS,
            puzzle_date__lt=today,
        )
        count = stale_qs.update(status=ArcadeAttempt.STATUS_ABANDONED)
        self.stdout.write(
            self.style.SUCCESS(f"Successfully closed {count} stale arcade attempt(s).")
        )
