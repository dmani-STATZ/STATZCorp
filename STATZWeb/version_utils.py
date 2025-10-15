"""
Version management utilities for STATZ Corporation application.
Provides Git-based version information for display on the landing page.
"""

import subprocess
import os
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class VersionManager:
    """
    Manages version information derived from Git repository.
    Provides methods to get commit hash, short hash, commit date, and formatted version strings.
    """
    
    def __init__(self, repo_path: Optional[str] = None):
        """
        Initialize the VersionManager.
        
        Args:
            repo_path: Path to the Git repository. If None, uses current directory.
        """
        self.repo_path = repo_path or os.getcwd()
        self._git_available = self._check_git_availability()
    
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
    
    def get_version_info(self) -> Dict[str, str]:
        """
        Get comprehensive version information.
        
        Returns:
            Dictionary containing version information
        """
        version_info = {
            'commit_hash': self.get_commit_hash() or 'unknown',
            'short_hash': self.get_short_hash() or 'unknown',
            'branch': self.get_branch_name() or 'unknown',
            'tag': self.get_tag_info() or 'none',
            'date': 'unknown'
        }
        
        commit_date = self.get_commit_date()
        if commit_date:
            version_info['date'] = commit_date.strftime('%Y-%m-%d')
        
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
