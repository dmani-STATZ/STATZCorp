"""
Version management utilities for STATZ Corporation application.
Provides version information for display on the landing page with multiple fallback methods.
"""

import subprocess
import os
import json
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class VersionManager:
    """
    Manages version information with multiple fallback methods.
    Provides methods to get commit hash, short hash, commit date, and formatted version strings.
    Falls back to environment variables, file-based tracking, and deployment timestamps.
    """
    
    def __init__(self, repo_path: Optional[str] = None):
        """
        Initialize the VersionManager.
        
        Args:
            repo_path: Path to the Git repository. If None, uses current directory.
        """
        self.repo_path = repo_path or os.getcwd()
        self._git_available = self._check_git_availability()
        self._version_file_path = os.path.join(self.repo_path, 'version_info.json')
    
    def _check_git_availability(self) -> bool:
        """Check if Git is available and the current directory is a Git repository."""
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--is-inside-work-tree'],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False
    
    def _run_git_command(self, command: list) -> Optional[str]:
        """
        Run a Git command and return the output.
        
        Args:
            command: List of command arguments (excluding 'git')
            
        Returns:
            Command output as string, or None if command fails
        """
        if not self._git_available:
            return None
            
        try:
            result = subprocess.run(
                ['git'] + command,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            logger.warning(f"Git command failed: {e}")
        
        return None
    
    def get_commit_hash(self) -> Optional[str]:
        """Get the full commit hash of the current HEAD."""
        return self._run_git_command(['rev-parse', 'HEAD'])
    
    def get_short_hash(self, length: int = 7) -> Optional[str]:
        """
        Get a shortened version of the commit hash.
        
        Args:
            length: Length of the short hash (default: 7)
        """
        return self._run_git_command(['rev-parse', f'--short={length}', 'HEAD'])
    
    def get_commit_date(self) -> Optional[datetime]:
        """Get the commit date of the current HEAD."""
        date_str = self._run_git_command(['log', '-1', '--format=%ci'])
        if date_str:
            try:
                return datetime.fromisoformat(date_str.replace(' ', 'T', 1).split()[0])
            except (ValueError, IndexError):
                pass
        return None
    
    def get_branch_name(self) -> Optional[str]:
        """Get the current branch name."""
        return self._run_git_command(['rev-parse', '--abbrev-ref', 'HEAD'])
    
    def get_tag_info(self) -> Optional[str]:
        """Get tag information for the current commit."""
        return self._run_git_command(['describe', '--tags', '--exact-match', 'HEAD'])
    
    def _get_environment_version_info(self) -> Dict[str, str]:
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
    
    def _get_file_version_info(self) -> Dict[str, str]:
        """Get version information from version_info.json file."""
        if not os.path.exists(self._version_file_path):
            return {}
        
        try:
            with open(self._version_file_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Could not read version file: {e}")
            return {}
    
    def _save_version_info(self, version_info: Dict[str, str]) -> None:
        """Save version information to version_info.json file."""
        try:
            with open(self._version_file_path, 'w') as f:
                json.dump(version_info, f, indent=2)
        except IOError as e:
            logger.warning(f"Could not save version file: {e}")
    
    def _get_deployment_timestamp(self) -> str:
        """Get deployment timestamp from Azure App Service or current time."""
        # Try Azure App Service deployment timestamp
        deployment_time = os.environ.get('WEBSITE_DEPLOYMENT_TIMESTAMP')
        if deployment_time:
            try:
                # Azure format: 2023-12-01T10:30:00Z
                dt = datetime.fromisoformat(deployment_time.replace('Z', '+00:00'))
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                pass
        
        # Fallback to file modification time of manage.py
        manage_py_path = os.path.join(self.repo_path, 'manage.py')
        if os.path.exists(manage_py_path):
            try:
                mtime = os.path.getmtime(manage_py_path)
                return datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')
            except OSError:
                pass
        
        # Final fallback to current time
        return datetime.now().strftime('%Y-%m-%d')

    def get_version_info(self) -> Dict[str, str]:
        """
        Get comprehensive version information with multiple fallback methods.
        
        Returns:
            Dictionary containing version information
        """
        # Start with empty version info
        version_info = {
            'commit_hash': '',
            'short_hash': '',
            'branch': '',
            'tag': 'none',
            'date': '',
            'build_number': '',
            'deployment_id': '',
        }
        
        # Try environment variables first (highest priority for production)
        env_info = self._get_environment_version_info()
        for key, value in env_info.items():
            if value:
                version_info[key] = value
        
        # Try file-based version (persistent storage)
        file_info = self._get_file_version_info()
        for key, value in file_info.items():
            if value and not version_info.get(key):
                version_info[key] = value
        
        # Fall back to Git information if nothing else available
        if not version_info.get('commit_hash'):
            version_info['commit_hash'] = self.get_commit_hash() or 'unknown'
        if not version_info.get('short_hash'):
            version_info['short_hash'] = self.get_short_hash() or 'unknown'
        if not version_info.get('branch'):
            version_info['branch'] = self.get_branch_name() or 'unknown'
        if not version_info.get('tag') or version_info['tag'] == 'none':
            version_info['tag'] = self.get_tag_info() or 'none'
        
        # Set date if still unknown
        if version_info['date'] == 'unknown':
            commit_date = self.get_commit_date()
            if commit_date:
                version_info['date'] = commit_date.strftime('%Y-%m-%d')
            else:
                version_info['date'] = self._get_deployment_timestamp()
        
        # Generate build number if not available
        if not version_info['build_number']:
            if version_info['deployment_id']:
                version_info['build_number'] = f"build-{version_info['deployment_id'][:8]}"
            elif version_info['short_hash'] != 'unknown':
                version_info['build_number'] = f"build-{version_info['short_hash']}"
            else:
                version_info['build_number'] = f"build-{datetime.now().strftime('%Y%m%d%H%M')}"
        
        # Save current version info for future use
        self._save_version_info(version_info)
        
        return version_info
    
    def get_display_version(self) -> str:
        """
        Get a user-friendly version string for display.
        
        Returns:
            Formatted version string
        """
        info = self.get_version_info()
        
        # If we have a tag, use it as the primary version
        if info['tag'] != 'none':
            return f"v{info['tag']} ({info['short_hash']})"
        
        # If we have a build number, use it
        if info['build_number']:
            return f"{info['build_number']} ({info['short_hash']})"
        
        # Otherwise, use branch and short hash
        return f"{info['branch']} ({info['short_hash']})"
    
    def get_detailed_version(self) -> str:
        """
        Get a detailed version string with more information.
        
        Returns:
            Detailed version string
        """
        info = self.get_version_info()
        
        if info['tag'] != 'none':
            return f"Version {info['tag']} - {info['short_hash']} ({info['date']})"
        elif info['build_number']:
            return f"Build {info['build_number']} - {info['short_hash']} ({info['date']})"
        else:
            return f"Branch: {info['branch']} - {info['short_hash']} ({info['date']})"


# Global instance for easy access
version_manager = VersionManager()


def get_version_info() -> Dict[str, str]:
    """Convenience function to get version information."""
    return version_manager.get_version_info()


def get_display_version() -> str:
    """Convenience function to get display version."""
    return version_manager.get_display_version()


def get_detailed_version() -> str:
    """Convenience function to get detailed version."""
    return version_manager.get_detailed_version()
