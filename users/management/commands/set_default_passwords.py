from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from django.db import transaction
import secrets
import string


class Command(BaseCommand):
    help = 'Set default passwords for users who don\'t have them'

    def add_arguments(self, parser):
        parser.add_argument(
            '--password-length',
            type=int,
            default=12,
            help='Length of generated passwords (default: 12)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )

    def generate_password(self, length=12):
        """Generate a secure random password"""
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        return password

    def handle(self, *args, **options):
        password_length = options['password_length']
        dry_run = options['dry_run']

        # Find users without passwords
        users_without_passwords = User.objects.filter(password__startswith='!')  # Django's unusable password marker

        if not users_without_passwords.exists():
            self.stdout.write(
                self.style.SUCCESS('All users already have passwords set.')
            )
            return

        self.stdout.write(
            f'Found {users_without_passwords.count()} users without passwords:'
        )

        passwords_set = []

        for user in users_without_passwords:
            password = self.generate_password(password_length)
            passwords_set.append((user.username, password))
            
            self.stdout.write(f'  {user.username}: {password}')

        if dry_run:
            self.stdout.write(
                self.style.WARNING('Dry run - no passwords were actually set.')
            )
            return

        # Confirm before proceeding
        confirm = input('\nProceed with setting these passwords? (y/N): ')
        if confirm.lower() != 'y':
            self.stdout.write('Operation cancelled.')
            return

        # Set passwords
        with transaction.atomic():
            for user in users_without_passwords:
                password = next(pwd for username, pwd in passwords_set if username == user.username)
                user.set_password(password)
                user.save()

        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully set passwords for {len(passwords_set)} users.'
            )
        )
        self.stdout.write(
            self.style.WARNING(
                'Please inform users of their new passwords securely.'
            )
        )
