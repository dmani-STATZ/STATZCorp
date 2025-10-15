"""
System test utilities for STATZ Corporation application.
Provides comprehensive testing of database connections, environment variables, and Azure services.
"""

import os
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Any
from django.conf import settings
from django.db import connection
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


class SystemTestResult:
    """Container for system test results."""
    
    def __init__(self, test_name: str, success: bool, message: str = "", details: Dict = None):
        self.test_name = test_name
        self.success = success
        self.message = message
        self.details = details or {}
        self.timestamp = datetime.now()


class SystemTester:
    """
    Comprehensive system testing utility for STATZ Corporation application.
    Tests database connections, environment variables, and Azure services.
    """
    
    def __init__(self):
        self.results: List[SystemTestResult] = []
    
    def add_result(self, test_name: str, success: bool, message: str = "", details: Dict = None):
        """Add a test result to the results list."""
        # Convert any Path objects to strings for JSON serialization
        if details:
            details = self._serialize_details(details)
        self.results.append(SystemTestResult(test_name, success, message, details))
    
    def _serialize_details(self, details: Dict) -> Dict:
        """Convert non-serializable objects in details to strings."""
        serialized = {}
        for key, value in details.items():
            if hasattr(value, '__str__') and not isinstance(value, (str, int, float, bool, list, dict)):
                serialized[key] = str(value)
            elif isinstance(value, dict):
                serialized[key] = self._serialize_details(value)
            elif isinstance(value, list):
                serialized[key] = [str(item) if hasattr(item, '__str__') and not isinstance(item, (str, int, float, bool)) else item for item in value]
            else:
                serialized[key] = value
        return serialized
    
    def test_database_connection(self) -> SystemTestResult:
        """Test database connection and basic operations."""
        test_name = "Database Connection"
        
        try:
            # Test basic connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                
                if result and result[0] == 1:
                    # Test database info
                    cursor.execute("SELECT @@VERSION")
                    version = cursor.fetchone()
                    
                    # Test table access (try to access a common table)
                    cursor.execute("SELECT COUNT(*) FROM information_schema.tables")
                    table_count = cursor.fetchone()
                    
                    details = {
                        'database_engine': settings.DATABASES['default']['ENGINE'],
                        'database_name': settings.DATABASES['default']['NAME'],
                        'database_host': settings.DATABASES['default'].get('HOST', 'N/A'),
                        'version': version[0] if version else 'Unknown',
                        'table_count': table_count[0] if table_count else 0,
                    }
                    
                    self.add_result(test_name, True, "Database connection successful", details)
                    return self.results[-1]
                else:
                    self.add_result(test_name, False, "Database query returned unexpected result")
                    return self.results[-1]
                    
        except Exception as e:
            self.add_result(test_name, False, f"Database connection failed: {str(e)}")
            return self.results[-1]
    
    def test_environment_variables(self) -> SystemTestResult:
        """Test critical environment variables for Azure deployment."""
        test_name = "Environment Variables"
        
        required_vars = [
            'DJANGO_SECRET_KEY',
            'DB_NAME',
            'DB_USER', 
            'DB_PASSWORD',
            'DB_HOST',
        ]
        
        optional_vars = [
            'MICROSOFT_AUTH_CLIENT_ID',
            'MICROSOFT_AUTH_CLIENT_SECRET',
            'MICROSOFT_AUTH_TENANT_ID',
            'MICROSOFT_AUTH_REDIRECT_URI',
            'REPORT_CREATOR_EMAIL',
        ]
        
        missing_required = []
        missing_optional = []
        present_vars = []
        
        # Check required variables
        for var in required_vars:
            if not os.environ.get(var):
                missing_required.append(var)
            else:
                present_vars.append(var)
        
        # Check optional variables
        for var in optional_vars:
            if not os.environ.get(var):
                missing_optional.append(var)
            else:
                present_vars.append(var)
        
        details = {
            'required_missing': missing_required,
            'optional_missing': missing_optional,
            'present_vars': present_vars,
            'total_checked': len(required_vars) + len(optional_vars),
        }
        
        if missing_required:
            self.add_result(test_name, False, 
                          f"Missing {len(missing_required)} required environment variables", 
                          details)
        else:
            self.add_result(test_name, True, 
                          f"All required environment variables present ({len(missing_optional)} optional missing)", 
                          details)
        
        return self.results[-1]
    
    def test_azure_services(self) -> SystemTestResult:
        """Test Azure-specific services and configurations."""
        test_name = "Azure Services"
        
        details = {}
        issues = []
        
        # Check if running on Azure
        is_azure = bool(os.environ.get('WEBSITE_SITE_NAME'))
        details['running_on_azure'] = is_azure
        
        if is_azure:
            details['website_name'] = os.environ.get('WEBSITE_SITE_NAME')
            details['azure_region'] = os.environ.get('WEBSITE_SITE_NAME', '').split('-')[0] if '-' in os.environ.get('WEBSITE_SITE_NAME', '') else 'Unknown'
        else:
            issues.append("Not running on Azure App Service")
        
        # Check Azure AD configuration
        azure_ad_config = getattr(settings, 'AZURE_AD_CONFIG', {})
        azure_ad_configured = all([
            azure_ad_config.get('app_id'),
            azure_ad_config.get('app_secret'),
            azure_ad_config.get('tenant_id'),
        ])
        
        details['azure_ad_configured'] = azure_ad_configured
        if not azure_ad_configured:
            issues.append("Azure AD configuration incomplete")
        
        # Check HTTPS settings
        https_redirect = getattr(settings, 'SECURE_SSL_REDIRECT', False)
        details['https_redirect_enabled'] = https_redirect
        
        # Check static files configuration
        static_storage = getattr(settings, 'STATICFILES_STORAGE', '')
        details['static_storage'] = static_storage
        if 'whitenoise' not in static_storage:
            issues.append("WhiteNoise not configured for static files")
        
        if issues:
            self.add_result(test_name, False, f"Azure services issues: {'; '.join(issues)}", details)
        else:
            self.add_result(test_name, True, "Azure services configured correctly", details)
        
        return self.results[-1]
    
    def test_django_settings(self) -> SystemTestResult:
        """Test Django settings configuration."""
        test_name = "Django Settings"
        
        details = {}
        issues = []
        
        # Check debug mode
        debug_mode = settings.DEBUG
        details['debug_mode'] = debug_mode
        if debug_mode and os.environ.get('WEBSITE_SITE_NAME'):
            issues.append("Debug mode enabled in production")
        
        # Check allowed hosts
        allowed_hosts = settings.ALLOWED_HOSTS
        details['allowed_hosts'] = allowed_hosts
        if not allowed_hosts or '*' in allowed_hosts:
            issues.append("ALLOWED_HOSTS not properly configured")
        
        # Check secret key
        secret_key = settings.SECRET_KEY
        details['secret_key_configured'] = bool(secret_key)
        details['secret_key_length'] = len(secret_key) if secret_key else 0
        if not secret_key or secret_key == 'django-insecure-1%a(rwepqwcb3)76hxfr*ino^y84977usbdg36h(f--o-s3s(=':
            issues.append("SECRET_KEY not properly configured")
        
        # Check database configuration
        db_config = settings.DATABASES['default']
        details['database_engine'] = db_config['ENGINE']
        details['database_name'] = db_config['NAME']
        details['database_host'] = db_config.get('HOST', 'N/A')
        
        if issues:
            self.add_result(test_name, False, f"Settings issues: {'; '.join(issues)}", details)
        else:
            self.add_result(test_name, True, "Django settings configured correctly", details)
        
        return self.results[-1]
    
    def test_static_files(self) -> SystemTestResult:
        """Test static files configuration."""
        test_name = "Static Files"
        
        details = {}
        issues = []
        
        # Check static files settings
        static_url = settings.STATIC_URL
        static_root = settings.STATIC_ROOT
        static_dirs = settings.STATICFILES_DIRS
        
        details['static_url'] = static_url
        details['static_root'] = str(static_root)
        details['static_dirs'] = [str(d) for d in static_dirs]
        
        # Check if static root exists
        if not static_root.exists():
            issues.append("STATIC_ROOT directory does not exist")
        
        # Check static files storage
        static_storage = settings.STATICFILES_STORAGE
        details['static_storage'] = static_storage
        
        if issues:
            self.add_result(test_name, False, f"Static files issues: {'; '.join(issues)}", details)
        else:
            self.add_result(test_name, True, "Static files configured correctly", details)
        
        return self.results[-1]
    
    def run_all_tests(self) -> List[SystemTestResult]:
        """Run all system tests and return results."""
        self.results = []  # Reset results
        
        # Run all tests
        self.test_database_connection()
        self.test_environment_variables()
        self.test_azure_services()
        self.test_django_settings()
        self.test_static_files()
        
        return self.results
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all test results."""
        total_tests = len(self.results)
        passed_tests = sum(1 for result in self.results if result.success)
        failed_tests = total_tests - passed_tests
        
        return {
            'total_tests': total_tests,
            'passed_tests': passed_tests,
            'failed_tests': failed_tests,
            'success_rate': (passed_tests / total_tests * 100) if total_tests > 0 else 0,
            'all_passed': failed_tests == 0,
        }


# Global instance for easy access
system_tester = SystemTester()


def run_system_tests() -> Tuple[List[SystemTestResult], Dict[str, Any]]:
    """
    Run all system tests and return results and summary.
    
    Returns:
        Tuple of (results_list, summary_dict)
    """
    results = system_tester.run_all_tests()
    summary = system_tester.get_summary()
    return results, summary
