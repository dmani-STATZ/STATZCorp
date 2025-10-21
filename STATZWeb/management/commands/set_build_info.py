"""
Management command to set build information for production deployments.
This command helps set up version information when Git is not available.
"""

from django.core.management.base import BaseCommand, CommandError
from STATZWeb.version_utils import version_manager
import os
import json
from datetime import datetime


class Command(BaseCommand):
    help = 'Set build information for production deployments'

    def add_arguments(self, parser):
        parser.add_argument(
            '--build-number',
            type=str,
            help='Build number to set (e.g., "build-123" or "v1.2.3")'
        )
        parser.add_argument(
            '--commit-hash',
            type=str,
            help='Git commit hash'
        )
        parser.add_argument(
            '--branch',
            type=str,
            help='Git branch name'
        )
        parser.add_argument(
            '--tag',
            type=str,
            help='Git tag name'
        )
        parser.add_argument(
            '--date',
            type=str,
            help='Build date (YYYY-MM-DD format)'
        )
        parser.add_argument(
            '--auto',
            action='store_true',
            help='Automatically generate build info from current state'
        )

    def handle(self, *args, **options):
        if options['auto']:
            self.set_auto_build_info()
        else:
            self.set_manual_build_info(options)

    def set_auto_build_info(self):
        """Automatically generate build information from current state."""
        self.stdout.write('Generating build information automatically...')
        
        # Get current version info
        version_info = version_manager.get_version_info()
        
        # Generate build number if not present
        if not version_info.get('build_number'):
            timestamp = datetime.now().strftime('%Y%m%d%H%M')
            version_info['build_number'] = f"build-{timestamp}"
        
        # Set date if not present
        if version_info.get('date') == 'unknown':
            version_info['date'] = datetime.now().strftime('%Y-%m-%d')
        
        # Save the version info
        version_manager._save_version_info(version_info)
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Build info set: {version_info["build_number"]} ({version_info["date"]})'
            )
        )

    def set_manual_build_info(self, options):
        """Set build information manually from command line arguments."""
        version_info = version_manager.get_version_info()
        
        # Update with provided values
        if options['build_number']:
            version_info['build_number'] = options['build_number']
        
        if options['commit_hash']:
            version_info['commit_hash'] = options['commit_hash']
            # Generate short hash if not provided
            if len(options['commit_hash']) > 7:
                version_info['short_hash'] = options['commit_hash'][:7]
        
        if options['branch']:
            version_info['branch'] = options['branch']
        
        if options['tag']:
            version_info['tag'] = options['tag']
        
        if options['date']:
            version_info['date'] = options['date']
        
        # Save the version info
        version_manager._save_version_info(version_info)
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Build info updated: {version_info["build_number"]} ({version_info["date"]})'
            )
        )
        
        # Display current version info
        self.stdout.write('\nCurrent version information:')
        for key, value in version_info.items():
            if value:
                self.stdout.write(f'  {key}: {value}')
