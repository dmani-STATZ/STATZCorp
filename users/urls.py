from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .ms_views import MicrosoftAuthView, MicrosoftCallbackView
from .debug_auth import DebugAuthView

app_name = 'users'

urlpatterns = [
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', auth_views.LogoutView.as_view(template_name='users/logout.html'), name='logout'),
    path('profile/', views.profile, name='profile'),
    path('password-reset/', 
         auth_views.PasswordResetView.as_view(template_name='users/password_reset.html'), 
         name='password_reset'),
    path('password-reset/done/', 
         auth_views.PasswordResetDoneView.as_view(template_name='users/password_reset_done.html'), 
         name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', 
         auth_views.PasswordResetConfirmView.as_view(template_name='users/password_reset_confirm.html'), 
         name='password_reset_confirm'),
    path('password-reset-complete/', 
         auth_views.PasswordResetCompleteView.as_view(template_name='users/password_reset_complete.html'), 
         name='password_reset_complete'),
    path('permission-denied/', views.permission_denied, name='permission_denied'),
    path('test-app-name/', views.test_app_name, name='test_app_name'),
    path('debug/permissions/', views.debug_app_permissions, name='debug_permissions'),
    # Company switching (superuser only)
    path('switch-company/', views.switch_company, name='switch_company'),
    
    # User settings URLs
    path('settings/view/', views.user_settings_view, name='settings-view'),
    path('settings/ajax/get/', views.ajax_get_user_setting, name='settings-get'),
    path('settings/ajax/save/', views.ajax_save_setting, name='settings-save'),
    path('settings/ajax/types/', views.ajax_get_setting_types, name='settings-types'),
    
    # Password management URLs
    path('password-change/', views.password_change_view, name='password_change'),
    path('password-set/', views.password_set_view, name='password_set'),
    
    # OAuth migration URLs
    path('oauth-migration/', views.oauth_migration_view, name='oauth_migration'),
    path('oauth-password-set/', views.oauth_password_set_view, name='oauth_password_set'),
    path('custom-password-reset/', views.custom_password_reset, name='custom_password_reset'),
    
    # Microsoft Authentication URLs
    path('microsoft/login/', MicrosoftAuthView.as_view(), name='microsoft_login'),
    path('microsoft/auth-callback/', MicrosoftCallbackView.as_view(), name='microsoft_callback'),
    path('check-auth-method/', views.check_auth_method, name='check_auth_method'),
    
    # System Messages URLs
    path('messages/', views.SystemMessageListView.as_view(), name='messages'),
    path('messages/create/', views.CreateMessageView.as_view(), name='create-message'),
    path('messages/mark-read/<int:pk>/', views.MarkMessageReadView.as_view(), name='mark-message-read'),
    path('messages/mark-all-read/', views.MarkAllMessagesReadView.as_view(), name='mark-all-messages-read'),
    path('messages/unread-count/', views.GetUnreadCountView.as_view(), name='unread-message-count'),
    
    # Debug URLs
    path('debug/auth-config/', DebugAuthView.as_view(), name='debug_auth_config'),
] 
