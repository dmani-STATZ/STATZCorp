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

    # Portal APIs
    path('portal/dashboard/', views.portal_dashboard_data, name='portal_dashboard_data'),
    path('portal/sections/', views.portal_sections_api, name='portal_sections_api'),
    path('portal/sections/<int:section_id>/delete/', views.portal_section_delete, name='portal_section_delete'),
    path('portal/resources/upsert/', views.portal_resource_upsert, name='portal_resource_upsert'),
    path('portal/resources/<int:resource_id>/delete/', views.portal_resource_delete, name='portal_resource_delete'),
    path('portal/tasks/create/', views.portal_task_create, name='portal_task_create'),
    path('portal/events/create/', views.portal_event_create, name='portal_event_create'),
    path('portal/events/import/sharepoint/', views.portal_import_sharepoint_xlsx, name='portal_import_sharepoint_xlsx'),
    path('portal/events/import/ui/', views.sharepoint_import_ui, name='sharepoint_import_ui'),
    path('portal/events/export/csv/', views.portal_events_export_csv, name='portal_events_export_csv'),
    path('portal/events/feed/', views.portal_event_feed, name='portal_event_feed'),
    path('portal/events/<int:event_id>/detail/', views.portal_event_detail, name='portal_event_detail'),
    path('portal/events/<int:event_id>/attachments/upsert/', views.portal_event_attachment_upsert, name='portal_event_attachment_upsert'),
    path('portal/events/attachments/<int:attachment_id>/delete/', views.portal_event_attachment_delete, name='portal_event_attachment_delete'),
    path('portal/events/<int:event_id>/update/', views.portal_event_update, name='portal_event_update'),
    path('portal/events/<int:event_id>/delete/', views.portal_event_delete, name='portal_event_delete'),
    path('portal/nlp-schedule/', views.portal_nlp_schedule, name='portal_nlp_schedule'),
    path('portal/microbreaks/create/', views.portal_microbreak_create, name='portal_microbreak_create'),
    path('portal/microbreaks/feed/', views.portal_microbreak_feed, name='portal_microbreak_feed'),
] 
