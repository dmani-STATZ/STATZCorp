from .settings import *
import os

# Security Settings
DEBUG = True  # Temporarily to see detailed errors
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')

# Update ALLOWED_HOSTS with your production domain
ALLOWED_HOSTS = [
    'statzutil01',
    '10.103.10.13',
    '127.0.0.1',
    'localhost',
    # Add your production IP addresses here
]

# Explicitly configure template directories
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            os.path.join(BASE_DIR, 'templates'),
            os.path.join(BASE_DIR, 'users', 'templates'),
            os.path.join(BASE_DIR, 'contracts', 'templates'),
            os.path.join(BASE_DIR, 'inventory', 'templates'),
            os.path.join(BASE_DIR, 'accesslog', 'templates'),
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'contracts.context_processors.reminders_processor',
            ],
        },
    },
]

# Static and Media Files Configuration
STATIC_URL = '/static/'  # Make sure this matches your Apache Alias
MEDIA_URL = '/media/'    # Make sure this matches your Apache Alias

STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Additional locations of static files
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

# Security Headers
SECURE_SSL_REDIRECT = False
# SESSION_COOKIE_SECURE = True
# CSRF_COOKIE_SECURE = False
# SECURE_BROWSER_XSS_FILTER = True
# SECURE_CONTENT_TYPE_NOSNIFF = True
# X_FRAME_OPTIONS = 'DENY'
# SECURE_HSTS_SECONDS = 31536000  # 1 year
# SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# SECURE_HSTS_PRELOAD = True

# Session Security
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = False

# Database Configuration
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
    }
}

# CORS Settings
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
CORS_EXPOSE_HEADERS = ['Content-Type', 'X-CSRFToken']
CORS_ALLOW_HEADERS = ['Content-Type', 'X-CSRFToken']

# Logging Configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'logs/django.log'),
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': True,
        },
        'users': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': True,
        },
        'STATZWeb': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}

# Microsoft Azure AD Authentication Settings
AZURE_AD_CONFIG = {
    'app_id': os.environ.get('MICROSOFT_APP_ID', 'b1c048a6-ece2-4bc2-a1fb-0db007a7e23a'),
    'app_secret': os.environ.get('MICROSOFT_APP_SECRET', 'LhJ8Q~mDFyzWnzUofKVoBN8DGKRg.DYlnZJ4Jdbd'),
    'tenant_id': os.environ.get('MICROSOFT_TENANT_ID', 'a6446842-5c7a-4655-aca7-2b819ecf2d64'),
    'redirect_uri': os.environ.get('MICROSOFT_REDIRECT_URI', 'https://statzutil01/users/microsoft/callback/'),
    'scopes': ['https://graph.microsoft.com/User.Read'],  # Use proper Graph API scopes, avoid reserved scopes
    'auto_create_user': True,
}

# Email Configuration
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('EMAIL_HOST')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_USER')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_PASSWORD')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER) 


# Might need to install LibreOffice to convert docx to pdf on the server
#https://www.libreoffice.org/download/download-libreoffice/
