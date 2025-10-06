import logging
import msal
from django.conf import settings
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View
from django.http import HttpResponse
from django.contrib.auth import authenticate, login
from .azure_auth import MicrosoftAuthBackend

logger = logging.getLogger(__name__)

class MicrosoftAuthView(View):
    """
    View to initiate the Microsoft authentication flow
    """
    def get(self, request):
        logger.info("Microsoft auth view accessed")
        
        # Clear any previous auth errors
        if 'microsoft_auth_error' in request.session:
            del request.session['microsoft_auth_error']
        
        # Check if Azure AD is properly configured
        if not settings.AZURE_AD_CONFIG.get('app_id') or not settings.AZURE_AD_CONFIG.get('tenant_id'):
            logger.error("Microsoft authentication is not properly configured. Missing app_id or tenant_id.")
            request.session['microsoft_auth_error'] = 'Microsoft authentication is not properly configured. Please contact your administrator.'
            return redirect('users:login')
        
        # Store the next URL if provided
        next_url = request.GET.get('next')
        if next_url:
            request.session['microsoft_auth_next'] = next_url
        
        try:
            # Initialize MSAL app
            app = msal.ConfidentialClientApplication(
                client_id=settings.AZURE_AD_CONFIG['app_id'],
                client_credential=settings.AZURE_AD_CONFIG['app_secret'],
                authority=f"{settings.AZURE_AD_CONFIG.get('authority', 'https://login.microsoftonline.us')}/{settings.AZURE_AD_CONFIG['tenant_id']}"
            )
        except Exception as e:
            logger.error(f"Error initializing MSAL app: {str(e)}")
            request.session['microsoft_auth_error'] = 'Authentication service is temporarily unavailable. Please try again later.'
            return redirect('users:login')
        
        # Generate auth URL with correct scope handling
        auth_url = app.get_authorization_request_url(
            scopes=settings.AZURE_AD_CONFIG['scopes'],
            redirect_uri=settings.AZURE_AD_CONFIG['redirect_uri'],
            state=request.session.session_key or "stateless",
            prompt="select_account"  # Force account selection each time
        )
        
        logger.debug(f"Generated Microsoft auth URL (truncated): {auth_url[:100]}...")
        
        # Store login attempt in session for tracking
        request.session['microsoft_auth_pending'] = True
        request.session.save()
        
        # Redirect to Microsoft login
        return redirect(auth_url)


class MicrosoftCallbackView(View):
    """
    View to handle the Microsoft authentication callback
    """
    def get(self, request):
        logger.info("Microsoft callback GET received")
        
        # Check for error parameter from Microsoft
        error = request.GET.get('error')
        error_description = request.GET.get('error_description')
        
        if error:
            logger.error(f"Microsoft auth error: {error} - {error_description}")
            # Store error in session
            request.session['microsoft_auth_error'] = error_description or "Authentication failed"
            request.session['microsoft_auth_pending'] = False
            request.session['microsoft_auth_success'] = False
            request.session.save()
            return redirect('users:login')
        
        # Handle GET request without code - likely a redirect issue
        code = request.GET.get('code')
        if not code:
            logger.warning("Callback received without code parameter")
            request.session['microsoft_auth_error'] = "No authorization code received"
            request.session['microsoft_auth_pending'] = False
            request.session['microsoft_auth_success'] = False
            request.session.save()
            return redirect('users:login')
            
        # Process the auth code
        return self._process_auth_code(request, code)
        
    def post(self, request):
        logger.info("Microsoft callback POST received")
        
        # Check for error parameter from Microsoft
        error = request.POST.get('error')
        error_description = request.POST.get('error_description')
        
        if error:
            logger.error(f"Microsoft auth error: {error} - {error_description}")
            # Store error in session
            request.session['microsoft_auth_error'] = error_description or "Authentication failed"
            request.session['microsoft_auth_pending'] = False
            request.session['microsoft_auth_success'] = False
            request.session.save()
            return redirect('users:login')
        
        # Get code from POST data
        code = request.POST.get('code')
        if not code:
            logger.warning("Callback received without code parameter")
            request.session['microsoft_auth_error'] = "No authorization code received"
            request.session['microsoft_auth_pending'] = False
            request.session['microsoft_auth_success'] = False
            request.session.save()
            return redirect('users:login')
            
        # Process the auth code
        return self._process_auth_code(request, code)
    
    def _process_auth_code(self, request, auth_code):
        """
        Process the authentication code received from Microsoft
        """
        logger.debug("Processing auth code")
        
        # Clean up session
        request.session['microsoft_auth_pending'] = False
        
        # Authenticate user with auth code
        user = authenticate(request, auth_code=auth_code)
        
        if user:
            # Log in the user
            login(request, user)
            logger.info(f"User {user.username} authenticated successfully via Microsoft")
            
            # Set success flag and save session
            request.session['microsoft_auth_success'] = True
            
            # Get the next URL if it was stored
            next_url = request.session.pop('microsoft_auth_next', None)
            request.session.save()
            
            # Redirect to next URL if it exists, otherwise to default
            if next_url:
                logger.info(f"Redirecting to stored next URL: {next_url}")
                return redirect(next_url)
            return redirect(settings.LOGIN_REDIRECT_URL)
        else:
            # Authentication failed
            logger.error("Microsoft authentication failed")
            request.session['microsoft_auth_error'] = "Authentication failed"
            request.session['microsoft_auth_success'] = False
            request.session.save()
            return redirect('users:login')


# Utility function to generate Microsoft login URL
def get_microsoft_login_url(request):
    """
    Generate Microsoft login URL for template use
    """
    try:
        # Check if Azure AD is properly configured
        if not settings.AZURE_AD_CONFIG.get('app_id') or not settings.AZURE_AD_CONFIG.get('tenant_id'):
            logger.error("Microsoft authentication is not properly configured. Missing app_id or tenant_id.")
            return None
        
        # Initialize MSAL app
        app = msal.ConfidentialClientApplication(
            client_id=settings.AZURE_AD_CONFIG['app_id'],
            client_credential=settings.AZURE_AD_CONFIG['app_secret'],
            authority=f"{settings.AZURE_AD_CONFIG.get('authority', 'https://login.microsoftonline.us')}/{settings.AZURE_AD_CONFIG['tenant_id']}"
        )
        
        # Generate auth URL using correct scopes
        auth_url = app.get_authorization_request_url(
            scopes=settings.AZURE_AD_CONFIG['scopes'],
            redirect_uri=settings.AZURE_AD_CONFIG['redirect_uri'],
            state=request.session.session_key or "stateless"
        )
        
        return auth_url
    except Exception as e:
        logger.exception(f"Error generating Microsoft login URL: {str(e)}")
        return None 