"""
Debug utilities for Microsoft authentication
"""
import logging
from django.conf import settings
from django.http import JsonResponse
from django.views import View
from .azure_auth import MicrosoftAuthBackend

logger = logging.getLogger(__name__)

class DebugAuthView(View):
    """
    Debug view to test Microsoft authentication configuration
    """
    def get(self, request):
        """Return current Azure AD configuration (without secrets)"""
        config = {
            'app_id': settings.AZURE_AD_CONFIG.get('app_id', 'NOT_SET'),
            'tenant_id': settings.AZURE_AD_CONFIG.get('tenant_id', 'NOT_SET'),
            'redirect_uri': settings.AZURE_AD_CONFIG.get('redirect_uri', 'NOT_SET'),
            'authority': settings.AZURE_AD_CONFIG.get('authority', 'NOT_SET'),
            'graph_endpoint': settings.AZURE_AD_CONFIG.get('graph_endpoint', 'NOT_SET'),
            'scopes': settings.AZURE_AD_CONFIG.get('scopes', []),
            'auto_create_user': settings.AZURE_AD_CONFIG.get('auto_create_user', False),
        }
        
        # Check if secrets are set (without revealing them)
        config['app_secret_set'] = bool(settings.AZURE_AD_CONFIG.get('app_secret') and 
                                      settings.AZURE_AD_CONFIG.get('app_secret') != 'YOUR_CLIENT_SECRET_HERE')
        
        return JsonResponse({
            'status': 'success',
            'config': config,
            'auth_backends': settings.AUTHENTICATION_BACKENDS
        })
