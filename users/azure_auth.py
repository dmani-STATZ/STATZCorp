import msal
from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
import logging
import uuid
import requests

logger = logging.getLogger(__name__)
User = get_user_model()

class MicrosoftAuthBackend(ModelBackend):
    """
    Authentication backend for Microsoft Azure AD.
    This backend authenticates a user against Microsoft Azure AD using MSAL.
    """
    
    def get_microsoft_auth_token(self, auth_code):
        """
        Get Microsoft auth token from authorization code
        """
        logger.debug("Attempting to get Microsoft auth token")
        try:
            # Initialize MSAL app
            app = msal.ConfidentialClientApplication(
                client_id=settings.AZURE_AD_CONFIG['app_id'],
                client_credential=settings.AZURE_AD_CONFIG['app_secret'],
                authority=f"https://login.microsoftonline.com/{settings.AZURE_AD_CONFIG['tenant_id']}"
            )
            
            # Get token from authorization code
            result = app.acquire_token_by_authorization_code(
                code=auth_code,
                scopes=settings.AZURE_AD_CONFIG['scopes'],
                redirect_uri=settings.AZURE_AD_CONFIG['redirect_uri']
            )
            
            logger.debug(f"Auth token result keys: {result.keys()}")
            
            if "error" in result:
                logger.error(f"Error getting Microsoft auth token: {result.get('error')} - {result.get('error_description')}")
                return None
                
            return result
        except Exception as e:
            logger.exception(f"Exception getting Microsoft auth token: {str(e)}")
            return None
    
    def get_microsoft_user_info(self, access_token):
        """
        Get Microsoft user info from access token
        """
        logger.debug("Attempting to get Microsoft user info")
        try:
            # Initialize MSAL app
            app = msal.ConfidentialClientApplication(
                client_id=settings.AZURE_AD_CONFIG['app_id'],
                client_credential=settings.AZURE_AD_CONFIG['app_secret'],
                authority=f"https://login.microsoftonline.com/{settings.AZURE_AD_CONFIG['tenant_id']}"
            )
            
            # Get user info from Microsoft Graph API
            result = app.acquire_token_on_behalf_of(
                user_assertion=access_token,
                scopes=['User.Read']
            )
            
            if "error" in result:
                logger.error(f"Error getting Microsoft user info: {result.get('error')} - {result.get('error_description')}")
                return None
                
            return result
        except Exception as e:
            logger.exception(f"Exception getting Microsoft user info: {str(e)}")
            return None
    
    def authenticate(self, request, auth_code=None, **kwargs):
        """
        Authenticate a user using Microsoft auth code
        """
        logger.debug("Microsoft authentication attempt")
        
        if not auth_code:
            logger.debug("No auth code provided")
            return None
            
        # Get token from auth code
        token_result = self.get_microsoft_auth_token(auth_code)
        if not token_result or "access_token" not in token_result:
            logger.error("Failed to get access token")
            return None
            
        # Extract user info from ID token claims
        id_token_claims = token_result.get("id_token_claims", {})
        logger.debug(f"ID token claims keys: {id_token_claims.keys() if id_token_claims else 'None'}")
        
        # If Microsoft Graph scopes were used, extract email from the token payload
        # or from the claims, depending on what's available
        email = None
        name = None
        oid = None
        
        if id_token_claims:
            # Get user info from ID token claims
            email = id_token_claims.get("email", id_token_claims.get("preferred_username"))
            name = id_token_claims.get("name", "")
            oid = id_token_claims.get("oid", "")  # Object ID in Azure AD
        
        # Try to get info from the access token claims as a fallback
        if not email and "access_token" in token_result:
            try:
                # Get user info using the access token with Microsoft Graph
                headers = {'Authorization': f'Bearer {token_result["access_token"]}'}
                graph_response = requests.get('https://graph.microsoft.com/v1.0/me', headers=headers)
                if graph_response.status_code == 200:
                    user_data = graph_response.json()
                    email = user_data.get("userPrincipalName", user_data.get("mail"))
                    name = user_data.get("displayName", "")
                    oid = user_data.get("id", "")
                    logger.debug(f"Got user info from Microsoft Graph: {email}")
            except Exception as e:
                logger.exception(f"Error getting user info from Microsoft Graph: {str(e)}")
        
        if not email:
            logger.error("No email found in claims or Microsoft Graph response")
            return None
            
        logger.info(f"Microsoft authentication for email: {email}")
        
        # Create or get user
        try:
            # Try to find user by email
            user = User.objects.get(email=email)
            logger.info(f"Found existing user: {user.username}")
            
            # Update Microsoft-specific information in session
            if request and hasattr(request, 'session'):
                request.session['microsoft_token'] = token_result.get('access_token')
                request.session['microsoft_token_expires'] = token_result.get('expires_in')
                request.session['microsoft_user_oid'] = oid
                request.session['microsoft_auth_success'] = True
                request.session['auth_method'] = 'microsoft'
                
            # Update user information if needed
            if name and (not user.first_name or not user.last_name):
                user.first_name = name.split(' ')[0] if ' ' in name else name
                user.last_name = name.split(' ')[1] if ' ' in name else ''
                user.save()
                
            return user
            
        except User.DoesNotExist:
            # Create a new user
            if settings.AZURE_AD_CONFIG.get('auto_create_user', True):
                logger.info(f"Creating new user with email: {email}")
                # Generate username from email or use part before @
                username = email.split('@')[0]
                
                # Ensure username is unique
                base_username = username
                counter = 1
                while User.objects.filter(username=username).exists():
                    username = f"{base_username}{counter}"
                    counter += 1
                
                # Create random password - user will login via Microsoft
                password = uuid.uuid4().hex
                
                # Create new user
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=name.split(' ')[0] if ' ' in name else name,
                    last_name=name.split(' ')[1] if ' ' in name else ''
                )
                logger.info(f"Created new user: {user.username}")
                
                # Store Microsoft-specific information in session
                if request and hasattr(request, 'session'):
                    request.session['microsoft_token'] = token_result.get('access_token')
                    request.session['microsoft_token_expires'] = token_result.get('expires_in')
                    request.session['microsoft_user_oid'] = oid
                    request.session['microsoft_auth_success'] = True
                    request.session['auth_method'] = 'microsoft'
                    
                return user
            else:
                logger.warning(f"User with email {email} does not exist and auto creation is disabled")
                return None 