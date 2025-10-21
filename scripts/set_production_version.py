#!/usr/bin/env python3
"""
Script to set version information for production deployments.
This script can be run during deployment to ensure version information is available.
"""

import os
import sys
import json
import subprocess
from datetime import datetime
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'STATZWeb.settings')

import django
django.setup()

from STATZWeb.version_utils import version_manager


def get_git_info():
    """Get Git information if available."""
    try:
        # Get commit hash
        commit_hash = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], 
            cwd=project_root,
            text=True
        ).strip()
        
        # Get short hash
        short_hash = subprocess.check_output(
            ['git', 'rev-parse', '--short=7', 'HEAD'], 
            cwd=project_root,
            text=True
        ).strip()
        
        # Get branch name
        branch = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'], 
            cwd=project_root,
            text=True
        ).strip()
        
        # Get commit date
        commit_date = subprocess.check_output(
            ['git', 'log', '-1', '--format=%ci'], 
            cwd=project_root,
            text=True
        ).strip()
        
        # Parse date
        try:
            date_obj = datetime.fromisoformat(commit_date.replace(' ', 'T', 1).split()[0])
            date_str = date_obj.strftime('%Y-%m-%d')
        except (ValueError, IndexError):
            date_str = datetime.now().strftime('%Y-%m-%d')
        
        # Try to get tag
        try:
            tag = subprocess.check_output(
                ['git', 'describe', '--tags', '--exact-match', 'HEAD'], 
                cwd=project_root,
                text=True
            ).strip()
        except subprocess.CalledProcessError:
            tag = 'none'
        
        return {
            'commit_hash': commit_hash,
            'short_hash': short_hash,
            'branch': branch,
            'tag': tag,
            'date': date_str
        }
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def get_environment_info():
    """Get version information from environment variables."""
    return {
        'commit_hash': os.environ.get('BUILD_COMMIT_HASH', ''),
        'short_hash': os.environ.get('BUILD_SHORT_HASH', ''),
        'branch': os.environ.get('BUILD_BRANCH', ''),
        'tag': os.environ.get('BUILD_TAG', ''),
        'date': os.environ.get('BUILD_DATE', ''),
        'build_number': os.environ.get('BUILD_NUMBER', ''),
        'deployment_id': os.environ.get('WEBSITE_DEPLOYMENT_ID', ''),
    }


def generate_build_number(info):
    """Generate a build number if not provided."""
    if info.get('build_number'):
        return info['build_number']
    
    if info.get('deployment_id'):
        return f"build-{info['deployment_id'][:8]}"
    
    if info.get('short_hash'):
        return f"build-{info['short_hash']}"
    
    timestamp = datetime.now().strftime('%Y%m%d%H%M')
    return f"build-{timestamp}"


def main():
    """Main function to set version information."""
    print("Setting up version information for production deployment...")
    
    # Start with environment variables
    version_info = get_environment_info()
    
    # Try to get Git info if not in environment
    if not any(version_info.values()):
        git_info = get_git_info()
        if git_info:
            version_info.update(git_info)
    
    # Generate build number if not provided
    version_info['build_number'] = generate_build_number(version_info)
    
    # Set date if not provided
    if not version_info.get('date'):
        version_info['date'] = datetime.now().strftime('%Y-%m-%d')
    
    # Clean up empty values
    version_info = {k: v for k, v in version_info.items() if v}
    
    # Save version info
    version_manager._save_version_info(version_info)
    
    print("Version information set successfully:")
    for key, value in version_info.items():
        print(f"  {key}: {value}")
    
    # Test the version display
    display_version = version_manager.get_display_version()
    detailed_version = version_manager.get_detailed_version()
    
    print(f"\nDisplay version: {display_version}")
    print(f"Detailed version: {detailed_version}")


if __name__ == '__main__':
    main()
