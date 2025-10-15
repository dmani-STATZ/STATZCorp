from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from django.db import transaction


class Command(BaseCommand):
    help = 'Set password for a user'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str, help='Username of the user')
        parser.add_argument('password', type=str, help='New password for the user')
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force password change even if user already has a password',
        )

    def handle(self, *args, **options):
        username = options['username']
        password = options['password']
        force = options['force']

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f'User "{username}" does not exist')

        if user.has_usable_password() and not force:
            raise CommandError(
                f'User "{username}" already has a password. Use --force to override.'
            )

        with transaction.atomic():
            user.set_password(password)
            user.save()

        self.stdout.write(
            self.style.SUCCESS(f'Successfully set password for user "{username}"')
        )
