"""
WSGI config for STATZWeb project.

Optimized for Azure App Service deployment.
"""

import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'STATZWeb.settings')

application = get_wsgi_application()
