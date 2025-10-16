# STATZWeb/middleware.py
from django.shortcuts import redirect
from django.conf import settings
from django.urls import reverse, resolve
from users.models import AppPermission, AppRegistry
import logging

logger = logging.getLogger(__name__)

class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.public_urls = [
            '/users/login/',
            '/users/logout/',
            '/users/microsoft/login/',
            '/users/microsoft/callback/',
            '/users/password-reset/',
            '/users/password-reset/done/',
            '/users/password-reset-confirm/',
            '/users/password-reset-complete/',
            '/users/oauth-migration/',
            '/users/oauth-password-set/',
            '/users/custom-password-reset/',
            '/system-test/',  # System test page for troubleshooting
            '/api/system-test/',  # System test API endpoint
        ]
        #logger.info(f"Middleware initialized with public_urls: {self.public_urls}")

    def __call__(self, request):
        #logger.info(f"Middleware processing request: {request.path_info}")
        
        path = request.path_info
        
        # Always bypass auth for PWA resources and landing page
        if (path == '/' or  # Root URL (landing page)
            path.startswith('/manifest.json') or 
            path.startswith('/static/') or 
            path == '/sw.js' or
            path.endswith('.png') or 
            path.endswith('.ico') or
            path.endswith('.js') and 'sw.js' in path):
            return self.get_response(request)
        
        if settings.REQUIRE_LOGIN:
            #logger.debug(f"REQUIRE_LOGIN is enabled")
            
            if not request.user.is_authenticated:
                #logger.debug(f"User not authenticated, checking if path {path} is public")
                
                # Always allow Microsoft auth paths
                if '/microsoft/' in path or 'microsoft' in path:
                    logger.debug(f"Bypassing auth check for Microsoft path: {path}")
                    return self.get_response(request)
                    
                if not self.is_public_url(path):
                    # Properly construct the login URL using reverse()
                    login_url = reverse('users:login')
                    if request.path:
                        login_url = f"{login_url}?next={request.path}"
                    return redirect(login_url)

            if request.user.is_authenticated and not request.user.is_superuser:
                #logger.debug(f"User {request.user.username} (ID: {request.user.id}) is authenticated but not superuser")
                
                # Always allow Microsoft auth paths for authenticated users
                if '/microsoft/' in path or 'microsoft' in path:
                    logger.debug(f"Bypassing permission check for Microsoft path: {path}")
                    return self.get_response(request)
                
                # Check if path is in public URLs
                is_public = self.is_public_url(path)
                #logger.debug(f"Path {path} is {'public' if is_public else 'not public'}")
                
                if not is_public:
                    try:
                        resolved = resolve(request.path_info)
                        # Extract app_name from the namespace if available
                        app_name = resolved.namespace.split(':')[0] if resolved.namespace else resolved.app_name
                        
                        #logger.info(f"Request to: {request.path_info}, resolved namespace: '{resolved.namespace}', app_name: '{app_name}'")
                        
                        if app_name and app_name != 'admin' and app_name != 'users':
                            #logger.info(f"Checking permissions for app: {app_name}")
                            
                            # First, find the AppRegistry entry for this app_name
                            try:
                                app_registry = AppRegistry.objects.get(app_name=app_name)
                                #logger.info(f"Found AppRegistry entry for {app_name}: {app_registry.app_name} (ID: {app_registry.id})")
                                
                                # Then check if the user has permission for this app
                                try:
                                    permission = AppPermission.objects.get(
                                        user=request.user, 
                                        app_name=app_registry
                                    )
                                    #logger.info(f"Permission found for user {request.user.username} and app {app_name}: has_access={permission.has_access}")
                                    
                                    if not permission.has_access:
                                        #logger.info(f"Permission denied for: {request.path_info}")
                                        return redirect('permission_denied')
                                    else:
                                        #logger.info(f"Permission granted for: {request.path_info}")
                                        pass
                                except AppPermission.DoesNotExist:
                                    # If no permission record exists, deny access
                                    #logger.info(f"No permission record for user {request.user.username} and app {app_name}")
                                    return redirect('permission_denied')
                                    
                            except AppRegistry.DoesNotExist:
                                # If the app isn't registered, log it but allow access
                                #logger.warning(f"App {app_name} not found in AppRegistry")
                                pass
                        else:
                            #logger.info(f"App {app_name} is exempt from permission checks")
                            pass    
                    except Exception as e:
                        #logger.error(f"Error in middleware: {e}", exc_info=True)
                        # Consider whether to deny access on errors
                        # return redirect('permission_denied')
                        pass
                else:
                    #logger.info(f"Path {path} is in public_urls, skipping permission check")
                    pass

        response = self.get_response(request)
        
        # Set CORS headers for PWA resources
        if path == '/manifest.json':
            response['Content-Type'] = 'application/manifest+json'
            response['Access-Control-Allow-Origin'] = '*'
            response['Access-Control-Allow-Methods'] = '*'
            response['Access-Control-Allow-Headers'] = '*'
        elif path.endswith('sw.js') or path == '/sw.js' or path.endswith('/sw.js'):
            response['Service-Worker-Allowed'] = '/'
            response['Access-Control-Allow-Origin'] = '*'
        
        #logger.debug(f"Middleware completed for {request.path_info}")
        return response
        
    def is_public_url(self, path):
        """
        Check if a path is in the public URLs list.
        Uses exact matching for exact paths and prefix matching for paths ending with '/'.
        """
        # Check for PWA and static resources
        if (path.startswith('/manifest.json') or
            path.startswith('/static/') or
            path.startswith('/media/') or
            '/sw.js' in path or
            path.endswith('.png') or
            path.endswith('.ico')):
            return True
            
        # Check for Microsoft auth paths
        if '/microsoft/' in path or 'microsoft' in path or '/users/microsoft/' in path:
            return True
            
        # Exact match
        if path in self.public_urls:
            return True
            
        # Prefix match for admin, static, media paths
        for url in self.public_urls:
            # If the URL ends with '/', it's a prefix
            if url.endswith('/') and url != '/' and path.startswith(url):
                return True
                
        # Special case for root URL '/'
        if '/' in self.public_urls and path == '/':
            return True
                
        return False