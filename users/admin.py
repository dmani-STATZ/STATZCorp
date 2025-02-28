# users/admin.py
from django.contrib import admin
from .models import AppPermission, Announcement, AppRegistry
from django import forms
from django.contrib.auth.models import User
from django.apps import apps
from django.utils.safestring import mark_safe
from django.template.loader import render_to_string
import logging
from django.http import JsonResponse
from django.urls import path
from django.db import models

logger = logging.getLogger(__name__)

class AppPermissionForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter user field to only show active users
        self.fields['user'].queryset = User.objects.filter(is_active=True)
        
        # Get all registered apps
        registered_apps = AppRegistry.get_active_apps()
        
        # Add checkbox fields for each app
        for app in registered_apps:
            field_name = f'app_{app.app_name}'
            self.fields[field_name] = forms.BooleanField(
                label=app.display_name,
                required=False,
                initial=False
            )
            
        # If we're editing an existing user's permissions, set initial values
        if 'instance' in kwargs and kwargs['instance']:
            user = kwargs['instance'].user
            existing_permissions = AppPermission.objects.filter(user=user)
            for perm in existing_permissions:
                field_name = f'app_{perm.app_name.app_name}'
                self.fields[field_name].initial = perm.has_access

    class Meta:
        model = AppPermission
        fields = ['user']

class AppPermissionAdmin(admin.ModelAdmin):
    form = AppPermissionForm
    list_display = ('username', 'get_permissions_display')
    
    def username(self, obj):
        return obj.user.username
    username.short_description = 'User'
    
    def get_permissions_display(self, obj):
        # Get all active apps
        all_apps = AppRegistry.get_active_apps()
        # Get user's permissions
        user_permissions = {
            p.app_name.app_name: p.has_access 
            for p in AppPermission.objects.filter(user=obj.user)
        }
        
        display_items = []
        for app in all_apps:
            has_access = user_permissions.get(app.app_name, False)
            # Using Tailwind colors: green-500 for success, red-500 for denied
            bg_color = '#10b981' if has_access else '#ef4444'
            display_items.append(
                f'<span style="'
                f'background-color: {bg_color};'
                f'color: white;'
                f'padding: 2px 8px;'
                f'border-radius: 9999px;'  # Tailwind's full rounded
                f'margin: 0 2px;'
                f'display: inline-block;'
                f'font-size: 0.875rem;'    # Tailwind's text-sm
                f'font-weight: 500;'       # Tailwind's font-medium
                f'line-height: 1.25rem;'   # Tailwind's leading-5
                f'">{app.app_name} {"✓" if has_access else "✗"}</span>'
            )
        return mark_safe(''.join(display_items))
    get_permissions_display.short_description = 'App Permissions'

    def save_model(self, request, obj, form, change):
        """Override save_model to handle our custom permission saving"""
        user = form.cleaned_data['user']
        
        # Delete existing permissions for this user
        AppPermission.objects.filter(user=user).delete()
        
        # Create new permissions for checked boxes
        registered_apps = AppRegistry.get_active_apps()
        for app in registered_apps:
            field_name = f'app_{app.app_name}'
            if form.cleaned_data.get(field_name, False):
                AppPermission.objects.create(
                    user=user,
                    app_name=app,
                    has_access=True
                )
        
        # Don't call obj.save() - we've handled everything ourselves
        return None

    def response_add(self, request, obj, post_url_continue=None):
        """Handle redirect after adding"""
        return self.response_post_save_add(request, obj)

    def response_change(self, request, obj):
        """Handle redirect after editing"""
        return self.response_post_save_change(request, obj)

    def get_queryset(self, request):
        """Return one row per user by getting distinct users"""
        # Get users who have any permissions
        user_ids = AppPermission.objects.values_list('user_id', flat=True).distinct()
        # Get one permission record for each user (first one we find)
        return AppPermission.objects.filter(
            id__in=AppPermission.objects.filter(user_id__in=user_ids)
            .values('user_id')
            .annotate(min_id=models.Min('id'))
            .values_list('min_id', flat=True)
        ).select_related('user')

    def get_permissions_for_user(self, request):
        """API endpoint to get permissions for a specific user"""
        user_id = request.GET.get('user_id')
        if not user_id:
            return JsonResponse({'error': 'No user ID provided'}, status=400)
        
        try:
            user = User.objects.get(pk=user_id)
            permissions = AppPermission.get_permissions_for_user(user)
            return JsonResponse(permissions)
        except User.DoesNotExist:
            return JsonResponse({'error': 'User not found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('get-permissions/', self.admin_site.admin_view(self.get_permissions_for_user), name='get-user-permissions'),
        ]
        return custom_urls + urls

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        extra_context['show_save_and_add_another'] = False
        return super().change_view(request, object_id, form_url, extra_context)

    def add_view(self, request, form_url='', extra_context=None):
        extra_context = extra_context or {}
        extra_context['show_save_and_add_another'] = False
        return super().add_view(request, form_url, extra_context)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == 'user':
            field.label = 'Select User'
        return field

    class Media:
        js = ('admin/js/app_permissions.js',)

# Register your models here.
admin.site.register(AppPermission, AppPermissionAdmin)
admin.site.register(Announcement)
admin.site.register(AppRegistry)

