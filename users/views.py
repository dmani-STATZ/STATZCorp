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
from django.urls import resolve
import logging
from django.views.decorators.http import require_http_methods
import json
from .user_settings import UserSettings

logger = logging.getLogger(__name__)

def register(request):
    if request.user.is_authenticated:
        return redirect('index')  # redirect to main page if already logged in
    if request.method == "POST":
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            messages.success(request, f'Account created for {username}!')
            return redirect('index')
    else:
        form = UserRegisterForm()
    return render(request, 'users/register.html', {'form': form})


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
        setting_type = data.get('setting_type')
        value = data.get('value')
        
        if not setting_type or value is None:
            return JsonResponse({'success': False, 'error': 'Missing required fields'})
        
        success = UserSettings.save_setting(
            user=request.user,
            name=setting_type,
            value=value
        )
        
        return JsonResponse({
            'success': success,
            'message': 'Setting saved successfully' if success else 'Failed to save setting'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})