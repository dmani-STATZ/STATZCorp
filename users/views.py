from django.shortcuts import render, redirect
from django.contrib import messages
from .forms import UserRegisterForm, BaseForm, AdminLoginForm, PasswordChangeForm, PasswordSetForm, EmailLookupForm, OAuthPasswordSetForm
from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver
from STATZWeb.decorators import login_required
from django.http import JsonResponse
from django.contrib.auth.decorators import user_passes_test
from .models import AppPermission, UserSetting, UserSettingState, SystemMessage
from django.contrib.auth.models import User
from django.urls import resolve, reverse
import logging
from django.views.decorators.http import require_http_methods
import json
from .user_settings import UserSettings
from django.contrib.auth import get_user_model
from django.contrib.auth import authenticate, login as auth_login
from .ms_views import get_microsoft_login_url
from django.views.generic import ListView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.forms import AuthenticationForm
from django.conf import settings

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
    
    # Get the next URL from query parameters
    next_url = request.GET.get('next')
    
    # Check for Microsoft auth success
    if microsoft_auth_success:
        logger.debug(f"Microsoft auth successful, redirecting to: {next_url or 'index'}")
        return redirect(next_url or 'index')
    
    # Get Microsoft login URL
    microsoft_login_url = get_microsoft_login_url(request)
    if next_url:
        microsoft_login_url = f"{reverse('users:microsoft_login')}?next={next_url}"
    
    # Handle password login form
    password_form = None
    
    if request.method == 'POST' and 'password_login' in request.POST:
        password_form = AdminLoginForm(data=request.POST)
        if password_form.is_valid():
            username = password_form.cleaned_data.get('username')
            password = password_form.cleaned_data.get('password')
            user = authenticate(request, username=username, password=password)
            if user is not None:
                auth_login(request, user)
                messages.success(request, f'Welcome back, {user.username}!')
                return redirect(next_url or 'index')
            else:
                auth_error = 'Invalid username or password.'
        else:
            auth_error = 'Please correct the errors below.'
    else:
        password_form = AdminLoginForm()
    
    context = {
        'title': 'Login',
        'auth_error': auth_error,
        'microsoft_login_url': microsoft_login_url,
        'form': password_form,
    }
    
    return render(request, 'users/login.html', context)

def register(request):
    """Redirect registration to Microsoft authentication"""
    messages.info(request, 'New accounts are created through Microsoft authentication. Please sign in with Microsoft.')
    return redirect('users:microsoft_login')


@login_required
def profile(request):
    """User profile page showing account information and password management"""
    context = {
        'title': 'User Profile',
    }
    return render(request, 'users/profile.html', context)


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

class SystemMessageListView(LoginRequiredMixin, ListView):
    """View for displaying all system messages for a user."""
    
    model = SystemMessage
    template_name = 'users/system_messages.html'
    context_object_name = 'messages'
    
    def get_queryset(self):
        return SystemMessage.objects.filter(user=self.request.user)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['unread_count'] = SystemMessage.get_unread_count(self.request.user)
        return context

class MarkMessageReadView(LoginRequiredMixin, View):
    """View for marking a message as read."""
    
    def post(self, request, *args, **kwargs):
        message_id = kwargs.get('pk')
        try:
            message = SystemMessage.objects.get(id=message_id, user=request.user)
            message.mark_as_read()
            return JsonResponse({'status': 'success'})
        except SystemMessage.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Message not found'}, status=404)

class MarkAllMessagesReadView(LoginRequiredMixin, View):
    """View for marking all messages as read."""
    
    def post(self, request, *args, **kwargs):
        messages = SystemMessage.objects.filter(user=request.user, read_at__isnull=True)
        for message in messages:
            message.mark_as_read()
        return JsonResponse({'status': 'success'})

class GetUnreadCountView(LoginRequiredMixin, View):
    """View for getting the count of unread messages."""
    
    def get(self, request, *args, **kwargs):
        count = SystemMessage.get_unread_count(request.user)
        return JsonResponse({'count': count})

class CreateMessageView(LoginRequiredMixin, View):
    """View for creating and sending system messages to other users."""
    
    template_name = 'users/create_message.html'
    
    def get(self, request):
        # Get all active users except the current user
        available_users = User.objects.filter(is_active=True)
        #available_users = User.objects.filter(is_active=True).exclude(id=request.user.id)
        
        return render(request, self.template_name, {
            'available_users': available_users
        })
    
    def post(self, request):
        try:
            # Get recipients from comma-separated string
            recipients_str = request.POST.get('recipients', '')
            if not recipients_str:
                messages.error(request, 'Please select at least one recipient.')
                return redirect('users:create-message')
            
            # Split the string into a list of IDs
            recipient_ids = [int(id_str) for id_str in recipients_str.split(',') if id_str.strip()]
            
            # Get message details
            title = request.POST.get('title')
            message_content = request.POST.get('message')
            priority = request.POST.get('priority', 'medium')
            
            # Create message for each recipient
            recipients = User.objects.filter(id__in=recipient_ids)
            for recipient in recipients:
                SystemMessage.create_message(
                    user=recipient,
                    title=title,
                    message=message_content,
                    priority=priority,
                    source_app='users',
                    source_model='User',
                    source_id=str(request.user.id)
                )
            
            messages.success(request, f'Message sent to {len(recipients)} recipient(s).')
            return redirect('users:messages')
            
        except Exception as e:
            messages.error(request, f'Error sending message: {str(e)}')
            return redirect('users:create-message')

@login_required
def user_settings_view(request):
    """View for displaying and managing user settings."""
    # Get all settings for the current user
    current_user_settings = UserSettings.get_all_settings(request.user)
    
    # Get all possible setting types
    setting_types = UserSetting.objects.values_list('setting_type', flat=True).distinct()
    
    context = {
        'settings': current_user_settings,
        'setting_types': list(setting_types),
    }
    
    return render(request, 'users/settings_view.html', context)


@login_required
def password_change_view(request):
    """View for changing user password"""
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, data=request.POST)
        if form.is_valid():
            new_password = form.cleaned_data['new_password1']
            request.user.set_password(new_password)
            request.user.save()
            messages.success(request, 'Your password has been changed successfully.')
            return redirect('users:profile')
    else:
        form = PasswordChangeForm(request.user)
    
    context = {
        'title': 'Change Password',
        'form': form,
    }
    
    return render(request, 'users/password_change.html', context)


@login_required
def password_set_view(request):
    """View for setting initial password for users without one"""
    # Check if user already has a password
    if request.user.has_usable_password():
        messages.info(request, 'You already have a password set.')
        return redirect('users:profile')
    
    if request.method == 'POST':
        form = PasswordSetForm(data=request.POST)
        if form.is_valid():
            new_password = form.cleaned_data['new_password1']
            request.user.set_password(new_password)
            request.user.save()
            messages.success(request, 'Your password has been set successfully.')
            return redirect('users:profile')
    else:
        form = PasswordSetForm()
    
    context = {
        'title': 'Set Password',
        'form': form,
    }
    
    return render(request, 'users/password_set.html', context)


def oauth_migration_view(request):
    """View for OAuth users to set passwords - email lookup step"""
    if request.method == 'POST':
        form = EmailLookupForm(data=request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            try:
                user = User.objects.get(email=email)
                # Store user ID in session for next step
                request.session['oauth_migration_user_id'] = user.id
                messages.success(request, f'Account found for {email}. Please set your password.')
                return redirect('users:oauth_password_set')
            except User.DoesNotExist:
                messages.error(request, f'No account found with email: {email}')
        else:
            # Form has validation errors
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = EmailLookupForm()
    
    # Debug: Show all users with emails for testing
    all_users = User.objects.filter(email__isnull=False).exclude(email='')
    debug_info = f"Available emails: {', '.join([u.email for u in all_users[:5]])}"  # Show first 5
    
    context = {
        'title': 'Set Your Password',
        'form': form,
        'debug_info': debug_info,
    }
    
    return render(request, 'users/oauth_migration.html', context)


def oauth_password_set_view(request):
    """View for OAuth users to set passwords - password entry step"""
    # Check if user ID is in session
    user_id = request.session.get('oauth_migration_user_id')
    if not user_id:
        messages.error(request, 'Please start the password setup process from the beginning.')
        return redirect('users:oauth_migration')
    
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        messages.error(request, 'Invalid user. Please start over.')
        return redirect('users:oauth_migration')
    
    if request.method == 'POST':
        form = OAuthPasswordSetForm(user, data=request.POST)
        if form.is_valid():
            new_password = form.cleaned_data['new_password1']
            user.set_password(new_password)
            user.save()
            # Clear session
            del request.session['oauth_migration_user_id']
            # Log the user in with the first available backend
            backend = settings.AUTHENTICATION_BACKENDS[0] if settings.AUTHENTICATION_BACKENDS else 'django.contrib.auth.backends.ModelBackend'
            auth_login(request, user, backend=backend)
            messages.success(request, f'Welcome back, {user.first_name or user.username}! Your password has been set successfully.')
            return redirect('index')
        else:
            # Form has validation errors
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = OAuthPasswordSetForm(user)
    
    # Show appropriate message based on whether user already has a password
    if user.has_usable_password():
        password_status = "update your password"
    else:
        password_status = "set your password"
    
    context = {
        'title': 'Set Your Password',
        'form': form,
        'user': user,
        'password_status': password_status,
    }
    
    return render(request, 'users/oauth_password_set.html', context)


def custom_password_reset(request):
    """Custom password reset that redirects OAuth users to migration flow"""
    if request.method == 'POST':
        email = request.POST.get('email')
        if email:
            try:
                user = User.objects.get(email=email)
                if not user.has_usable_password():
                    # OAuth user - redirect to migration flow
                    request.session['oauth_migration_user_id'] = user.id
                    messages.info(request, 'OAuth user detected. Redirecting to password setup...')
                    return redirect('users:oauth_password_set')
                else:
                    # Regular user - use standard password reset
                    return redirect('users:password_reset')
            except User.DoesNotExist:
                messages.error(request, 'No account found with this email address.')
    
    # Show email form
    form = EmailLookupForm()
    context = {
        'title': 'Password Reset',
        'form': form,
    }
    return render(request, 'users/custom_password_reset.html', context)