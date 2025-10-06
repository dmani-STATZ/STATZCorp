"""
Django development settings for STATZWeb project.

This file contains development-specific settings that override production settings.
Use this for local development with runserver.
"""

from .settings import *
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file for development
load_dotenv()

# Override DEBUG for development
DEBUG = True

# Development-specific ALLOWED_HOSTS
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', [
    'statzweb.azurewebsites.us',
    'statzutil01',
    '127.0.0.1',
    'localhost',
    '0.0.0.0',  # For Docker if needed
]).split(',')

# Development database - SQLite for simplicity
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Development-specific security settings (less restrictive)
SECURE_SSL_REDIRECT = False
SECURE_PROXY_SSL_HEADER = None
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

# Development CSRF settings
CSRF_TRUSTED_ORIGINS = [
    'http://127.0.0.1:8000',
    'http://localhost:8000',
]

# Development session settings
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_SAMESITE = 'Lax'

# Development CORS settings (more permissive for local development)
CORS_ALLOW_ALL_ORIGINS = True

# Development logging (cleaner output)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
        'clean': {
            'format': '{levelname}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'clean',
        },
        'file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'django_dev.log',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.autoreload': {
            'handlers': ['file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'STATZWeb': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': True,
        },
        'users': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': True,
        },
        'contracts': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': True,
        },
        'processing': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}

# Development-specific middleware (remove some production middleware)
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_browser_reload.middleware.BrowserReloadMiddleware',
    'STATZWeb.middleware.LoginRequiredMiddleware',
]

# Development static files (no WhiteNoise compression)
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

# Development cache (simple in-memory)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake-dev',
    }
}

# Development session engine
SESSION_ENGINE = 'django.contrib.sessions.backends.db'

# Development email settings (console backend for testing)
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Development-specific Azure AD settings (can be overridden by environment)
# For development, you can either:
# 1. Set up Azure AD credentials (recommended for testing)
# 2. Set REQUIRE_LOGIN=False to bypass authentication entirely
AZURE_AD_CONFIG = {
    'app_id': os.environ.get('MICROSOFT_AUTH_CLIENT_ID', ''),
    'app_secret': os.environ.get('MICROSOFT_AUTH_CLIENT_SECRET', ''),
    'tenant_id': os.environ.get('MICROSOFT_AUTH_TENANT_ID', ''),
    'redirect_uri': os.environ.get('MICROSOFT_AUTH_REDIRECT_URI', 'http://localhost:8000/microsoft/auth-callback/'),
    'authority': os.environ.get('MICROSOFT_AUTH_AUTHORITY', 'https://login.microsoftonline.us'),
    'graph_endpoint': os.environ.get('MICROSOFT_AUTH_GRAPH_ENDPOINT', 'https://graph.microsoft.us'),
    'scopes': ['https://graph.microsoft.us/User.Read'],
    'auto_create_user': True,
}

# Debug Azure AD configuration
print(f"🔍 Azure AD Debug Info:")
print(f"   App ID: {'SET' if AZURE_AD_CONFIG['app_id'] else 'NOT SET'}")
print(f"   Tenant ID: {'SET' if AZURE_AD_CONFIG['tenant_id'] else 'NOT SET'}")
print(f"   Client Secret: {'SET' if AZURE_AD_CONFIG['app_secret'] else 'NOT SET'}")
print(f"   Authority: {AZURE_AD_CONFIG['authority']}")
print(f"   Redirect URI: {AZURE_AD_CONFIG['redirect_uri']}")

# Development-specific settings
# Set to True to require login in development, False to bypass login
REQUIRE_LOGIN = os.getenv('REQUIRE_LOGIN', 'True').lower() == 'true'

# Development file upload limits (more permissive)
DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024  # 50MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024  # 50MB
DATA_UPLOAD_MAX_NUMBER_FIELDS = 5000

# Development PDF processing limits
PDF_MAX_PAGES = 2000
PDF_MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

print("🔧 Development settings loaded - DEBUG=True, SQLite database, verbose logging enabled")
