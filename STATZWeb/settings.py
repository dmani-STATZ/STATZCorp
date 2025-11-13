"""
Django settings for STATZWeb project.

Handles both development and production environments.
- Development: Uses .env file for configuration
- Production: Uses Azure App Service environment variables
"""

from pathlib import Path
import os
from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file for development (if available)
try:
    from dotenv import load_dotenv
    load_dotenv()
    #print("Check: .env file loaded successfully")
except ImportError:
    print("Warning: python-dotenv not installed, install it with: pip install python-dotenv")
    print("   Continuing without .env file - using environment variables")
except Exception as e:
    print(f"Warning: Could not load .env file: {e}")
    print("   Continuing with environment variables")

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-dev-key-change-in-production-1234567890abcdef')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DJANGO_DEBUG', 'False').lower() == 'true'

# Determine if we're in production (Azure App Service)
IS_PRODUCTION = os.environ.get('WEBSITE_SITE_NAME') is not None

# Azure App Service configuration
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 
    'statzweb.azurewebsites.us,127.0.0.1,localhost,169.254.130.1,169.254.130.2,169.254.130.5,.azurewebsites.us'
).split(',')

# CORS settings for PWA
CORS_ALLOW_ALL_ORIGINS = not DEBUG  # Restrict in production
CORS_ALLOW_CREDENTIALS = True
CORS_EXPOSE_HEADERS = ['Content-Type', 'X-CSRFToken']
CORS_ALLOW_HEADERS = ['Content-Type', 'X-CSRFToken', 'Authorization']
CORS_ALLOW_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']

# PWA settings
SECURE_CROSS_ORIGIN_OPENER_POLICY = None  # Helps with PWA compatibility

# Application definition

INSTALLED_APPS = [
    'STATZWeb',
    'users.apps.UsersConfig',
    'inventory.apps.InventoryConfig',
    'contracts.apps.ContractsConfig',
    'accesslog.apps.AccesslogConfig',
    'td_now.apps.TDNowConfig',
    'crispy_forms',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'tailwind',
    'theme_tw',
    'corsheaders',
    'django_extensions',
    'processing.apps.ProcessingConfig',
    'training.apps.TrainingConfig',
    'reports.apps.ReportsConfig',
]

# Middleware - Environment aware
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'users.middleware.ActiveCompanyMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'STATZWeb.middleware.LoginRequiredMiddleware',
]

if IS_PRODUCTION:
    # Production middleware
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')  # Azure static file serving
else:
    # Development middleware
    MIDDLEWARE.append('django_browser_reload.middleware.BrowserReloadMiddleware')
    INSTALLED_APPS.append('django_browser_reload')

# Session settings
SESSION_COOKIE_AGE = 3600  # seconds
SESSION_EXPIRE_AT_BROWSER_CLOSE = True  # Session expires when browser is closed
SESSION_SAVE_EVERY_REQUEST = True  # Refresh the session on every request
SESSION_COOKIE_SECURE = not DEBUG  # Force HTTPS for session cookies in production
SESSION_COOKIE_HTTPONLY = True  # Prevent JavaScript from accessing the session cookie
SESSION_COOKIE_SAMESITE = 'Lax'  # Options: 'Lax', 'Strict', or 'None'

ROOT_URLCONF = 'STATZWeb.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': ['templates'], 
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'contracts.context_processors.reminders_processor',
                'users.context_processors.user_preferences',
                'users.context_processors.unread_messages',
                'users.context_processors.active_company',
                'STATZWeb.context_processors.version_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'STATZWeb.wsgi.application'


# Database Configuration
# Production: Azure SQL Database via environment variables
# Development: SQLite (can be overridden with environment variables)

if IS_PRODUCTION:
    # Production: Azure SQL Database
    required_db_vars = ['DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST']
    missing_vars = [var for var in required_db_vars if not os.environ.get(var)]
    if missing_vars:
        raise ImproperlyConfigured(f"Missing required database environment variables: {', '.join(missing_vars)}")
    
    DATABASES = {
        'default': {
            'ENGINE': 'mssql',
            'NAME': os.environ.get('DB_NAME'),
            'USER': os.environ.get('DB_USER'),
            'PASSWORD': os.environ.get('DB_PASSWORD'),
            'HOST': os.environ.get('DB_HOST'),
            'OPTIONS': {
                'driver': 'ODBC Driver 17 for SQL Server',
                'timeout': 60,
                'autocommit': True,
                'extra_params': 'Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=60;',
            },
        },
    }
else:
    # Development: SQLite (default) or SQL Server (if environment variables are set)
    if os.environ.get('DB_HOST') and os.environ.get('DB_NAME'):
        print("Using SQL Server for development (from environment variables)")
        DATABASES = {
            'default': {
                'ENGINE': 'mssql',
                'NAME': os.environ.get('DB_NAME'),
                'USER': os.environ.get('DB_USER'),
                'PASSWORD': os.environ.get('DB_PASSWORD'),
                'HOST': os.environ.get('DB_HOST'),
                'OPTIONS': {
                    'driver': 'ODBC Driver 17 for SQL Server',
                    'timeout': 60,
                    'autocommit': True,
                    'extra_params': 'Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=60;',
                },
            },
        }
    else:
        print("Using SQLite for development")
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': BASE_DIR / 'db.sqlite3',
            },
        }


# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'America/Chicago'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images) - Environment aware
STATIC_URL = '/static/'
MEDIA_URL = '/media/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Uploaded media storage
# In production, avoid storing uploads inside the app folder (wwwroot),
# since deployments overwrite that directory. Use a persistent path instead.
if IS_PRODUCTION:
    _default_media_root = Path('D:/home/media') if os.name == 'nt' else Path('/home/site/media')
    MEDIA_ROOT = Path(os.environ.get('APP_MEDIA_ROOT', _default_media_root))
else:
    MEDIA_ROOT = BASE_DIR / 'media'

# Ensure the media directory exists to prevent runtime errors on first write
try:
    Path(MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
except Exception:
    # Don't fail settings import if directory cannot be created
    pass
STATICFILES_DIRS = [BASE_DIR / 'static']

if IS_PRODUCTION:
    # Production: Azure App Service static file serving with WhiteNoise
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
    WHITENOISE_USE_FINDERS = True
    WHITENOISE_AUTOREFRESH = False
else:
    # Development: Standard static files storage
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

REPORT_CREATOR_EMAIL = os.environ.get('REPORT_CREATOR_EMAIL', 'dmani@statzcorp.com')
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
OPENROUTER_HTTP_REFERER = os.environ.get('OPENROUTER_HTTP_REFERER', 'http://localhost:8000/')
OPENROUTER_X_TITLE = os.environ.get('OPENROUTER_X_TITLE', 'STATZCorp Reports')
# Default model can be overridden via env; switch to minimax free by default
OPENROUTER_MODEL = os.environ.get('OPENROUTER_MODEL', 'minimax/minimax-m2:free')
# Allow overriding base URL in case of proxy or routing issues
OPENROUTER_BASE_URL = os.environ.get('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')

# Optional: a comma-separated list of fallback models to try if the primary
# model is not available for this API key/providers.
_fallbacks = os.environ.get('OPENROUTER_MODEL_FALLBACKS', '')
OPENROUTER_MODEL_FALLBACKS = [m.strip() for m in _fallbacks.split(',') if m.strip()]

# Default primary key field type
# https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CRISPY_ALLOWED_TEMPLATE_PACKS = "tailwind"
CRISPY_TEMPLATE_PACK = "tailwind"

# Email settings removed - using Windows authentication instead

# Authentication settings
LOGIN_REDIRECT_URL = 'index'
LOGOUT_REDIRECT_URL = 'landing'
LOGIN_URL = 'users:login'

# Custom authentication toggle - Environment aware
REQUIRE_LOGIN = os.getenv('REQUIRE_LOGIN', 'False' if not IS_PRODUCTION else 'True').lower() == 'true'

TAILWIND_APP_NAME = 'theme_tw'

INTERNAL_IPS = [
    "127.0.0.1","localhost"
]

NPM_BIN_PATH = "C:\\Program Files\\nodejs\\npm.cmd"

# Logging configuration - Environment aware
if IS_PRODUCTION:
    # Production logging
    LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'simple': {
                'format': '{levelname} {message}',
                'style': '{',
            },
        },
        'handlers': {
            'console': {
                'level': 'INFO',
                'class': 'logging.StreamHandler',
                'formatter': 'simple',
            },
        },
        'loggers': {
            'django': {
                'handlers': ['console'],
                'level': 'INFO',
                'propagate': True,
            },
            'STATZWeb': {
                'handlers': ['console'],
                'level': 'INFO',
                'propagate': True,
            },
        },
    }
else:
    # Development logging (more verbose)
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

# Security settings - Environment aware
if IS_PRODUCTION:
    # Production security settings
    SECURE_SSL_REDIRECT = True  # Force HTTPS in production
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')  # Azure App Service
    CSRF_COOKIE_SECURE = True  # Force HTTPS for CSRF cookies in production
    SECURE_HSTS_SECONDS = 31536000  # 1 year in production
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True  # Force HTTPS for session cookies in production
else:
    # Development security settings (less restrictive)
    SECURE_SSL_REDIRECT = False
    SECURE_PROXY_SSL_HEADER = None
    CSRF_COOKIE_SECURE = False
    SECURE_HSTS_SECONDS = 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False
    SESSION_COOKIE_SECURE = False  # Allow HTTP in development

# Common security headers
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'DENY'  # Prevent clickjacking
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

# Database connection security will be handled in the database configuration section above

# CSRF settings - Environment aware
if IS_PRODUCTION:
    CSRF_TRUSTED_ORIGINS = [
        'https://statzweb.azurewebsites.us',
        'https://*.azurewebsites.us',
    ]
else:
    CSRF_TRUSTED_ORIGINS = [
        'http://127.0.0.1:8000',
        'http://localhost:8000',
    ]

# Input validation settings to prevent various attacks
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB max file size
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB max file size
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000  # Prevent DoS via large forms

# PDF processing security - mitigate PDF processing vulnerabilities (migrated to pypdf)
PDF_MAX_PAGES = 1000  # Limit PDF processing to prevent infinite loops
PDF_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB max PDF size

# Azure AD Configuration
# Production: Requires environment variables
# Development: Optional, can be configured via .env file

if IS_PRODUCTION:
    # Production: Validate required Azure AD environment variables
    required_azure_vars = ['MICROSOFT_AUTH_CLIENT_ID', 'MICROSOFT_AUTH_CLIENT_SECRET', 'MICROSOFT_AUTH_TENANT_ID']
    missing_azure_vars = [var for var in required_azure_vars if not os.environ.get(var)]
    if missing_azure_vars:
        raise ImproperlyConfigured(f"Missing required Azure AD environment variables: {', '.join(missing_azure_vars)}")

AZURE_AD_CONFIG = {
    'app_id': os.environ.get('MICROSOFT_AUTH_CLIENT_ID', ''),
    'app_secret': os.environ.get('MICROSOFT_AUTH_CLIENT_SECRET', ''),
    'tenant_id': os.environ.get('MICROSOFT_AUTH_TENANT_ID', ''),
    'redirect_uri': os.environ.get('MICROSOFT_AUTH_REDIRECT_URI', 
        'https://statzweb.azurewebsites.us/microsoft/auth-callback/' if IS_PRODUCTION 
        else 'http://localhost:8000/microsoft/auth-callback/'),
    'authority': os.environ.get('MICROSOFT_AUTH_AUTHORITY', 'https://login.microsoftonline.us'),
    'graph_endpoint': os.environ.get('MICROSOFT_AUTH_GRAPH_ENDPOINT', 'https://graph.microsoft.us'),
    'scopes': ['https://graph.microsoft.us/User.Read'],
    'auto_create_user': True,
}

# Debug Azure AD configuration
#print(f"   Azure AD Debug Info:")
#print(f"   App ID: {'SET' if AZURE_AD_CONFIG['app_id'] else 'NOT SET'}")
#print(f"   Tenant ID: {'SET' if AZURE_AD_CONFIG['tenant_id'] else 'NOT SET'}")
#print(f"   Client Secret: {'SET' if AZURE_AD_CONFIG['app_secret'] else 'NOT SET'}")
#print(f"   Authority: {AZURE_AD_CONFIG['authority']}")
#print(f"   Redirect URI: {AZURE_AD_CONFIG['redirect_uri']}")


# Add Microsoft Auth backend to authentication backends
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',  # Default Django backend
    'users.azure_auth.MicrosoftAuthBackend',  # Microsoft Azure AD backend
]

# Performance optimizations - Environment aware
if IS_PRODUCTION:
    # Production performance optimizations
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'unique-snowflake',
        }
    }
    DATABASES['default']['CONN_MAX_AGE'] = 60
    SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'
else:
    # Development performance settings
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'unique-snowflake-dev',
        }
    }
    SESSION_ENGINE = 'django.contrib.sessions.backends.db'

# Print environment summary
#print(f"   Settings loaded - Environment: {'PRODUCTION' if IS_PRODUCTION else 'DEVELOPMENT'}")
#print(f"   Debug: {DEBUG}")
#print(f"   Database: {'SQL Server' if IS_PRODUCTION or os.environ.get('DB_HOST') else 'SQLite'}")
#print(f"   Login Required: {REQUIRE_LOGIN}")
#print(f"   Azure AD: {'CONFIGURED' if AZURE_AD_CONFIG['app_id'] else 'NOT CONFIGURED'}")
