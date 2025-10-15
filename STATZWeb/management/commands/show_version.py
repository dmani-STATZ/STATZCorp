"""
Django management command to display version information.
Useful for testing and debugging version functionality.
"""

from django.core.management.base import BaseCommand
from STATZWeb.version_utils import get_version_info, get_display_version, get_detailed_version


class Command(BaseCommand):
    help = 'Display version information derived from Git repository'

    def handle(self, *args, **options):
        """Display version information."""
        self.stdout.write(self.style.SUCCESS('STATZ Corporation Version Information'))
        self.stdout.write('=' * 50)
        
        # Get version info
        version_info = get_version_info()
        display_version = get_display_version()
        detailed_version = get_detailed_version()
        
        # Display information
        self.stdout.write(f'Display Version: {display_version}')
        self.stdout.write(f'Detailed Version: {detailed_version}')
        self.stdout.write('')
        self.stdout.write('Raw Version Info:')
        for key, value in version_info.items():
            self.stdout.write(f'  {key}: {value}')
        
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Version information retrieved successfully!'))
