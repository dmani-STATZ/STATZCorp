from django.shortcuts import render, redirect
from django.contrib import messages
from .forms import UserRegisterForm
from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver
from STATZWeb.decorators import login_required
from django.http import JsonResponse
from django.contrib.auth.decorators import user_passes_test
from .models import AppPermission, UserSetting, UserSettingState
from django.contrib.auth.models import User
from django.urls import resolve, reverse
import logging
from django.views.decorators.http import require_http_methods
import json
from .user_settings import UserSettings
from django.contrib.auth import get_user_model
from django.contrib.auth import authenticate, login as auth_login
from .ms_views import get_microsoft_login_url

logger = logging.getLogger(__name__)

def login_view(request):
    """Custom login view that redirects to Microsoft authentication"""
    # Clear previous auth errors
    auth_error = None
    microsoft_auth_success = request.session.get('microsoft_auth_success', False)
    
    # Check for auth errors
    if 'microsoft_auth_error' in request.session:
        auth_error = request.session.pop('microsoft_auth_error')
        logger.warning(f"Microsoft auth error: {auth_error}")
    
    # Check if already authenticated
    if request.user.is_authenticated:
        logger.debug(f"User {request.user.username} is already authenticated")
        return redirect('index')
    
    # Check for Microsoft auth success
    if microsoft_auth_success:
        logger.debug("Microsoft auth successful, redirecting to index")
        return redirect('index')
    
    # Get the next URL from query parameters
    next_url = request.GET.get('next')
    
    # Get Microsoft login URL
    microsoft_login_url = get_microsoft_login_url(request)
    if next_url:
        microsoft_login_url = f"{reverse('users:microsoft_login')}?next={next_url}"
    
    context = {
        'auth_error': auth_error,
        'microsoft_login_url': microsoft_login_url,
        'admin_mode': request.GET.get('admin', False),
    }
    
    return render(request, 'users/login.html', context)

def register(request):
    """Redirect registration to Microsoft authentication"""
    messages.info(request, 'New accounts are created through Microsoft authentication. Please sign in with Microsoft.')
    return redirect('users:microsoft_login')


@login_required
def profile(request):
    return render(request, 'users/profile.html')


@receiver(user_logged_out)
def on_user_logged_out(sender, request, **kwargs):
    messages.success(request, 'You have been successfully logged out.')

def permission_denied(request):
    return render(request, 'users/permission_denied.html')

def is_staff(user):
    return user.is_staff

@user_passes_test(is_staff)
def debug_app_permissions(request):
    """A debug view to see all current app permissions in the database"""
    users = User.objects.all()
    
    # Build a dictionary of all permissions
    permissions_data = {}
    
    for user in users:
        permissions = AppPermission.objects.filter(user=user)
        user_permissions = {}
        
        for perm in permissions:
            user_permissions[perm.app_name_id] = perm.has_access
        
        permissions_data[user.username] = {
            'user_id': user.id,
            'permissions': user_permissions
        }
    
    return JsonResponse({
        'app_permissions': permissions_data,
        'total_users': users.count(),
        'total_permissions': AppPermission.objects.count()
    })

def test_app_name(request):
    """Test view to determine the current app_name"""
    resolved = resolve(request.path_info)
    app_name = resolved.app_name
    namespace = resolved.namespace
    url_name = resolved.url_name
    view_name = f"{namespace}:{url_name}" if namespace else url_name
    
    logger.info(f"app_name: {app_name}")
    logger.info(f"namespace: {namespace}")
    logger.info(f"url_name: {url_name}")
    logger.info(f"view_name: {view_name}")
    
    return JsonResponse({
        'app_name': app_name,
        'namespace': namespace,
        'url_name': url_name,
        'view_name': view_name,
        'path': request.path_info,
    })

@login_required
def save_user_setting(request):
    """Handle saving user settings via AJAX"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'})
    
    try:
        data = json.loads(request.body)
        print(f"Received setting data: {data}")  # Debug print
        setting_type = data.get('setting_type')
        value = data.get('value')
        
        if not setting_type or value is None:
            print(f"Missing required fields: setting_type={setting_type}, value={value}")  # Debug print
            return JsonResponse({'success': False, 'error': 'Missing required fields'})
        
        success = UserSettings.save_setting(
            user=request.user,
            name=setting_type,
            value=value
        )
        
        print(f"Save result: {success}")  # Debug print
        return JsonResponse({
            'success': success,
            'message': 'Setting saved successfully' if success else 'Failed to save setting'
        })
        
    except json.JSONDecodeError:
        print("Invalid JSON data received")  # Debug print
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        print(f"Error saving setting: {str(e)}")  # Debug print
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def manage_settings(request):
    """View for managing user settings."""
    User = get_user_model()
    
    # Only get active users
    users = User.objects.filter(is_active=True)
    
    # Get all settings for the current user
    current_user_settings = UserSettings.get_all_settings(request.user)
    
    # Get all possible setting names from the database
    all_settings = UserSetting.objects.all().values_list('name', flat=True).distinct()
    
    # Add debug info
    logger.debug(f"Manage settings view: Found {users.count()} active users, {len(current_user_settings)} settings for current user, and {len(all_settings)} total unique settings")
    
    context = {
        'users': users,
        'current_user_settings': current_user_settings,
        'all_settings': list(all_settings),
        'setting_types': ['string', 'boolean', 'integer', 'float'],  # Available setting types
    }
    
    return render(request, 'users/manage_settings.html', context)

@login_required
@require_http_methods(["POST"])
def ajax_save_setting(request):
    """AJAX endpoint for saving user settings."""
    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
        setting_name = data.get('setting_name')
        setting_value = data.get('setting_value')
        setting_type = data.get('setting_type', 'string')
        
        User = get_user_model()
        user = User.objects.get(id=user_id)
        
        # Convert value based on setting type
        if setting_type == 'boolean':
            setting_value = setting_value.lower() == 'true'
        elif setting_type == 'integer':
            setting_value = int(setting_value)
        elif setting_type == 'float':
            setting_value = float(setting_value)
        
        success = UserSettings.save_setting(
            user=user,
            name=setting_name,
            value=setting_value,
            setting_type=setting_type
        )
        
        return JsonResponse({
            'success': success,
            'message': 'Setting saved successfully' if success else 'Failed to save setting'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=400)

@login_required
@require_http_methods(["GET"])
def ajax_get_user_setting(request):
    """AJAX endpoint for getting a user's settings."""
    try:
        user_id = request.GET.get('user_id')
        setting_name = request.GET.get('setting_name')
        
        logger.debug(f"ajax_get_user_setting called for user_id={user_id}, setting_name={setting_name}")
        
        if not user_id:
            return JsonResponse({
                'success': False,
                'message': 'User ID is required'
            }, status=400)
        
        User = get_user_model()
        user = User.objects.get(id=user_id)
        
        if setting_name:
            # Get specific setting
            value = UserSettings.get_setting(user, setting_name)
            logger.debug(f"Returning specific setting {setting_name}={value}")
            return JsonResponse({
                'success': True,
                'value': value
            })
        else:
            # Get all settings
            settings = UserSettings.get_all_settings(user)
            logger.debug(f"Returning all settings for user {user.username}: {settings}")
            return JsonResponse({
                'success': True,
                'settings': settings
            })
            
    except User.DoesNotExist:
        logger.error(f"User not found: {user_id}")
        return JsonResponse({
            'success': False,
            'message': 'User not found'
        }, status=404)
    except Exception as e:
        logger.error(f"Error getting user settings: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': f"Error: {str(e)}"
        }, status=400)

@login_required
@require_http_methods(["GET"])
def ajax_get_setting_types(request):
    """AJAX endpoint for getting all setting types."""
    try:
        # Import here to avoid circular imports
        from .models import UserSetting
        
        # Get all settings with their types
        settings = UserSetting.objects.all()
        
        # Create dictionary of setting name to type
        types_dict = {setting.name: setting.setting_type for setting in settings}
        
        logger.debug(f"Returning {len(types_dict)} setting types")
        
        return JsonResponse({
            'success': True,
            'types': types_dict
        })
    except Exception as e:
        logger.error(f"Error getting setting types: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': f"Error: {str(e)}"
        }, status=400)

@login_required
def check_auth_method(request):
    """
    Check and display the user's authentication method
    For debugging purposes
    """
    auth_method = request.session.get('auth_method', 'unknown')
    logger.info(f"User {request.user.username} authenticated via {auth_method}")
    
    # Check if microsoft token exists
    ms_token = request.session.get('microsoft_token', None)
    ms_token_status = "exists" if ms_token else "missing"
    
    return JsonResponse({
        'username': request.user.username,
        'email': request.user.email,
        'auth_method': auth_method,
        'microsoft_token_status': ms_token_status,
        'is_authenticated': request.user.is_authenticated,
    })