from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .ms_views import MicrosoftAuthView, MicrosoftCallbackView

app_name = 'users'

urlpatterns = [
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', auth_views.LogoutView.as_view(template_name='users/logout.html'), name='logout'),
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
    path('settings/save/', views.save_user_setting, name='save_user_setting'),
    path('settings/view/', views.manage_settings, name='manage_settings'),
    path('settings/ajax/save/', views.ajax_save_setting, name='ajax_save_setting'),
    path('settings/ajax/get/', views.ajax_get_user_setting, name='ajax_get_user_setting'),
    path('settings/ajax/types/', views.ajax_get_setting_types, name='ajax_get_setting_types'),
    
    # Microsoft Authentication URLs
    path('microsoft/login/', MicrosoftAuthView.as_view(), name='microsoft_login'),
    path('microsoft/callback/', MicrosoftCallbackView.as_view(), name='microsoft_callback'),
    path('check-auth-method/', views.check_auth_method, name='check_auth_method'),
] 