"""
Django settings for STATZWeb project.

Optimized for Azure App Service deployment.
"""

from pathlib import Path
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-1%a(rwepqwcb3)76hxfr*ino^y84977usbdg36h(f--o-s3s(=')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DJANGO_DEBUG', 'False').lower() == 'true'

# Azure App Service configuration
ALLOWED_HOSTS = [
    'statzweb.azurewebsites.us',
    '127.0.0.1',
    'localhost',
    '.azurewebsites.us',  # Allow all Azure subdomains
]

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
    'crispy_forms',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'django_browser_reload',
    'tailwind',
    'theme_tw',
    'corsheaders',
    'django_extensions',
    'processing.apps.ProcessingConfig',
    'training.apps.TrainingConfig',
    'reports.apps.ReportsConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Azure static file serving
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
            ],
        },
    },
]

WSGI_APPLICATION = 'STATZWeb.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases


# Database configuration - Azure App Service optimized
if os.environ.get('WEBSITE_SITE_NAME'):  # Running on Azure App Service
    DATABASES = {
        'default': {
            'ENGINE': 'mssql',
            'NAME': os.environ.get('DB_NAME'),
            'USER': os.environ.get('DB_USER'),
            'PASSWORD': os.environ.get('DB_PASSWORD'),
            'HOST': os.environ.get('DB_HOST'),
            'OPTIONS': {
                'driver': 'ODBC Driver 17 for SQL Server',
            },
        },
    }
else:  # Local development
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


# Static files (CSS, JavaScript, Images) - Azure optimized
STATIC_URL = '/static/'
MEDIA_URL = '/media/'

STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_ROOT = BASE_DIR / 'media'

STATICFILES_DIRS = [
    BASE_DIR / 'static'
]

# Azure App Service static file serving with WhiteNoise
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# WhiteNoise configuration for Azure
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = DEBUG

# Reports app settings
REPORT_CREATOR_EMAIL = os.environ.get('REPORT_CREATOR_EMAIL', 'dmani@statzcorp.com')

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

# Custom authentication toggle
REQUIRE_LOGIN = os.getenv('REQUIRE_LOGIN', 'False').lower() == 'true'

TAILWIND_APP_NAME = 'theme_tw'

INTERNAL_IPS = [
    "127.0.0.1","localhost"
]

NPM_BIN_PATH = "C:\\Program Files\\nodejs\\npm.cmd"

# Logging configuration - Azure App Service optimized
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
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

# Security settings - Azure App Service optimized
SECURE_SSL_REDIRECT = not DEBUG  # Force HTTPS in production
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')  # Azure App Service
CSRF_COOKIE_SECURE = not DEBUG  # Force HTTPS for CSRF cookies in production
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0  # 1 year in production
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG

# CSRF settings for Azure
CSRF_TRUSTED_ORIGINS = [
    'https://statzweb.azurewebsites.us',
    'https://*.azurewebsites.us',
]

# Additional security headers to prevent vulnerabilities
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'DENY'  # Prevent clickjacking
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

# SQL Injection protection - ensure proper ORM usage
# Django's ORM automatically escapes parameters, but add extra validation
USE_TZ = True  # Ensure timezone awareness

# Input validation settings to prevent various attacks
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB max file size
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB max file size
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000  # Prevent DoS via large forms

# PDF processing security - mitigate PyPDF2 vulnerabilities
PDF_MAX_PAGES = 1000  # Limit PDF processing to prevent infinite loops
PDF_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB max PDF size

# Azure AD Configuration - Environment variables only
AZURE_AD_CONFIG = {
    'app_id': os.environ.get('MICROSOFT_AUTH_CLIENT_ID'),
    'app_secret': os.environ.get('MICROSOFT_AUTH_CLIENT_SECRET'),
    'tenant_id': os.environ.get('MICROSOFT_AUTH_TENANT_ID'),
    'redirect_uri': os.environ.get('MICROSOFT_REDIRECT_URI', 'https://statzweb.azurewebsites.us/microsoft/auth-callback/'),
    'authority': os.environ.get('MICROSOFT_AUTH_AUTHORITY', 'https://login.microsoftonline.us'),
    'graph_endpoint': os.environ.get('MICROSOFT_AUTH_GRAPH_ENDPOINT', 'https://graph.microsoft.us'),
    'scopes': ['https://graph.microsoft.us/User.Read'],
    'auto_create_user': True,
}


# Add Microsoft Auth backend to authentication backends
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',  # Default Django backend
    'users.azure_auth.MicrosoftAuthBackend',  # Microsoft Azure AD backend
]

# Azure App Service Performance Optimizations
if not DEBUG:
    # Cache configuration for Azure
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'unique-snowflake',
        }
    }
    
    # Database connection optimization
    DATABASES['default']['CONN_MAX_AGE'] = 60
    
    # Session optimization
    SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'
    
    # Static file optimization
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
