import msal
from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
import logging
import uuid
import requests
from datetime import timedelta
from django.utils import timezone
from .models import UserOAuthToken

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
        
        # Get or create user and save token
        user = None
        try:
            user = User.objects.get(email=email)
            logger.info(f"Found existing user: {user.username}")
            
            # Update user information if needed
            if name and (not user.first_name or not user.last_name):
                user.first_name = name.split(' ')[0] if ' ' in name else name
                user.last_name = name.split(' ')[1] if ' ' in name else ''
                user.save()
                logger.info(f"Updated user info for {user.username}")

        except User.DoesNotExist:
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
            else:
                logger.warning(f"User with email {email} does not exist and auto creation is disabled")
                return None

        # If user exists (found or created), store/update the token
        if user:
            access_token = token_result.get('access_token')
            refresh_token = token_result.get('refresh_token')
            expires_in = token_result.get('expires_in')
            expires_at = None
            if expires_in:
                try:
                    expires_at = timezone.now() + timedelta(seconds=int(expires_in))
                except (ValueError, TypeError):
                    logger.warning(f"Could not parse expires_in value: {expires_in}")

            UserOAuthToken.objects.update_or_create(
                user=user,
                provider='microsoft', # Explicitly set provider
                defaults={
                    'access_token': access_token,
                    'refresh_token': refresh_token,
                    'expires_at': expires_at,
                    'updated_at': timezone.now() # Explicitly set updated_at on update
                }
            )
            logger.info(f"Stored/Updated Microsoft OAuth token for user {user.username}")

            # Update necessary session information (excluding raw token/expiry)
            if request and hasattr(request, 'session'):
                # Removed: request.session['microsoft_token'] = token_result.get('access_token')
                # Removed: request.session['microsoft_token_expires'] = token_result.get('expires_in')
                request.session['microsoft_user_oid'] = oid
                request.session['microsoft_auth_success'] = True
                request.session['auth_method'] = 'microsoft'
                logger.debug(f"Updated session for user {user.username}: oid, auth_success, auth_method")

            return user

        # This part should technically not be reached if user creation/finding logic is correct
        # but kept as a safeguard
        logger.error("User object was None after find/create logic.")
        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None

# --- Token Refresh Utility Functions ---

def _get_msal_app():
    """Helper function to initialize the MSAL Confidential Client Application."""
    try:
        return msal.ConfidentialClientApplication(
            client_id=settings.AZURE_AD_CONFIG['app_id'],
            client_credential=settings.AZURE_AD_CONFIG['app_secret'],
            authority=f"https://login.microsoftonline.com/{settings.AZURE_AD_CONFIG['tenant_id']}"
        )
    except KeyError as e:
        logger.error(f"Missing Azure AD config setting: {e}")
        return None
    except Exception as e:
        logger.exception(f"Error initializing MSAL application: {str(e)}")
        return None

def _refresh_microsoft_token(user_token: UserOAuthToken) -> bool:
    """Attempts to refresh the Microsoft OAuth token using the refresh token.

    Args:
        user_token: The UserOAuthToken object containing the refresh token.

    Returns:
        True if the token was successfully refreshed and saved, False otherwise.
    """
    if not user_token.refresh_token:
        logger.warning(f"No refresh token available for user {user_token.user.username} to attempt refresh.")
        return False

    app = _get_msal_app()
    if not app:
        return False

    logger.info(f"Attempting to refresh Microsoft token for user {user_token.user.username}")
    result = app.acquire_token_by_refresh_token(
        refresh_token=user_token.refresh_token,
        scopes=settings.AZURE_AD_CONFIG['scopes']
    )

    if "error" in result:
        logger.error(f"Error refreshing token for user {user_token.user.username}: {result.get('error')} - {result.get('error_description')}")
        # Consider if we should clear the invalid refresh token here
        # user_token.refresh_token = None
        # user_token.access_token = None
        # user_token.expires_at = None
        # user_token.save()
        return False

    # Successfully refreshed
    access_token = result.get('access_token')
    refresh_token = result.get('refresh_token') # May get a new refresh token
    expires_in = result.get('expires_in')
    expires_at = None
    if expires_in:
        try:
            expires_at = timezone.now() + timedelta(seconds=int(expires_in))
        except (ValueError, TypeError):
            logger.warning(f"Could not parse expires_in value during refresh: {expires_in}")

    # Update the token object
    user_token.access_token = access_token
    if refresh_token: # Only update if a new one was provided
        user_token.refresh_token = refresh_token
    user_token.expires_at = expires_at
    user_token.updated_at = timezone.now()
    user_token.save()

    logger.info(f"Successfully refreshed Microsoft token for user {user_token.user.username}")
    return True

def get_valid_microsoft_token(user: User) -> str | None:
    """Gets a valid Microsoft access token for the user, refreshing if necessary.

    Args:
        user: The User object.

    Returns:
        A valid access token string, or None if a valid token cannot be obtained.
    """
    if not user or not user.is_authenticated:
        logger.warning("get_valid_microsoft_token called with invalid user.")
        return None

    try:
        user_token = UserOAuthToken.objects.get(user=user, provider='microsoft')
    except UserOAuthToken.DoesNotExist:
        logger.warning(f"No Microsoft OAuth token found for user {user.username}")
        return None
    except Exception as e:
        logger.exception(f"Error retrieving token for user {user.username}: {str(e)}")
        return None

    if not user_token.is_expired:
        logger.debug(f"Existing token for user {user.username} is still valid.")
        return user_token.access_token

    # Token is expired, attempt refresh
    logger.info(f"Microsoft token for user {user.username} has expired. Attempting refresh.")
    if _refresh_microsoft_token(user_token):
        # Refresh successful, return the new token
        return user_token.access_token
    else:
        # Refresh failed or not possible
        logger.error(f"Failed to obtain a valid Microsoft token for user {user.username} after expiry.")
        return None 