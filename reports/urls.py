from django.urls import path
from . import views

app_name = "reports"

urlpatterns = [
    # User pages
    path("", views.user_dashboard, name="user_dashboard"),
    path("my/", views.user_dashboard, name="my_requests"),
    path("request/", views.request_report, name="request_report"),
    path("run/<uuid:pk>/", views.run_report, name="run_report"),
    path("export/<uuid:pk>/", views.export_report, name="export_report"),
    path("request-change/<uuid:pk>/", views.request_change, name="request_change"),

    # Admin workspace
    path("admin/", views.admin_dashboard, name="admin_dashboard"),
    path("admin/save/<uuid:pk>/", views.admin_save_sql, name="admin_save_sql"),
    path("admin/delete/<uuid:pk>/", views.admin_delete_request, name="admin_delete_request"),
    path("admin/preview/<uuid:pk>/", views.admin_preview_sql, name="admin_preview_sql"),
    path("admin/ai/stream/", views.admin_ai_stream, name="admin_ai_stream"),
    path("admin/ai/settings/", views.admin_save_ai_settings, name="admin_save_ai_settings"),
]
