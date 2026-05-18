"""Bulk-clear DraftContract locks older than LOCK_DURATION."""
from django.core.management.base import BaseCommand

from intake.locks import clear_expired
from intake.models import DraftContract


class Command(BaseCommand):
    help = 'Clear DraftContract locks older than the 30-minute expiry.'

    def handle(self, *args, **options):
        count = clear_expired(DraftContract)
        self.stdout.write(self.style.SUCCESS(f'Cleared {count} stale lock(s).'))
