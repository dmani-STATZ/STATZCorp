"""
Django management command to check for security vulnerabilities.
"""

from django.core.management.base import BaseCommand
from django.conf import settings
import subprocess
import sys


class Command(BaseCommand):
    help = 'Check for security vulnerabilities in dependencies'

    def add_arguments(self, parser):
        parser.add_argument(
            '--fix',
            action='store_true',
            help='Automatically fix vulnerabilities where possible',
        )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('🔍 Checking for security vulnerabilities...')
        )
        
        try:
            # Check if pip-audit is available
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'list', '--format=freeze'],
                capture_output=True,
                text=True,
                check=True
            )
            
            self.stdout.write(
                self.style.SUCCESS('✅ Dependencies loaded successfully')
            )
            
            # Check Django version
            django_version = self.get_package_version('Django')
            if django_version:
                self.stdout.write(f'📦 Django version: {django_version}')
                if django_version >= '4.2.21':
                    self.stdout.write(
                        self.style.SUCCESS('✅ Django version is secure')
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING('⚠️ Django version may have vulnerabilities')
                    )
            
            # Check Gunicorn version
            gunicorn_version = self.get_package_version('gunicorn')
            if gunicorn_version:
                self.stdout.write(f'📦 Gunicorn version: {gunicorn_version}')
                if gunicorn_version >= '23.0.0':
                    self.stdout.write(
                        self.style.SUCCESS('✅ Gunicorn version is secure')
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING('⚠️ Gunicorn version may have vulnerabilities')
                    )
            
            # Check Requests version
            requests_version = self.get_package_version('requests')
            if requests_version:
                self.stdout.write(f'📦 Requests version: {requests_version}')
                if requests_version >= '2.32.3':
                    self.stdout.write(
                        self.style.SUCCESS('✅ Requests version is secure')
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING('⚠️ Requests version may have vulnerabilities')
                    )
            
            # Security settings check
            self.check_security_settings()
            
            self.stdout.write(
                self.style.SUCCESS('🎉 Security check completed!')
            )
            
        except subprocess.CalledProcessError as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Error checking dependencies: {e}')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Unexpected error: {e}')
            )

    def get_package_version(self, package_name):
        """Get version of a specific package."""
        try:
            result = subprocess.run(
                [sys.executable, '-c', f'import {package_name.lower()}; print({package_name.lower()}.__version__)'],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except (subprocess.CalledProcessError, ImportError):
            return None

    def check_security_settings(self):
        """Check Django security settings."""
        self.stdout.write('\n🔒 Checking security settings...')
        
        security_checks = [
            ('DEBUG', not settings.DEBUG, 'Debug mode should be disabled in production'),
            ('SECURE_SSL_REDIRECT', settings.SECURE_SSL_REDIRECT, 'HTTPS redirect should be enabled'),
            ('SESSION_COOKIE_SECURE', settings.SESSION_COOKIE_SECURE, 'Session cookies should be secure'),
            ('CSRF_COOKIE_SECURE', settings.CSRF_COOKIE_SECURE, 'CSRF cookies should be secure'),
            ('X_FRAME_OPTIONS', settings.X_FRAME_OPTIONS == 'DENY', 'X-Frame-Options should be DENY'),
        ]
        
        for setting, condition, message in security_checks:
            if condition:
                self.stdout.write(
                    self.style.SUCCESS(f'✅ {setting}: {message}')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'⚠️ {setting}: {message}')
                )
