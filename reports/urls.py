from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    # Hub
    path("", views.reports_hub, name="hub"),

    # User actions
    path("request/submit/", views.submit_request, name="submit_request"),
    path("run/<uuid:pk>/", views.run_report, name="run_report"),
    path("export/<uuid:pk>/", views.export_report, name="export_report"),
    path("change/<uuid:pk>/", views.request_change, name="request_change"),
    path("promote/<uuid:pk>/", views.promote_to_company, name="promote_to_company"),
    path("share/<uuid:pk>/", views.share_report, name="share_report"),

    # Admin queue
    path("admin/", views.admin_queue, name="admin_queue"),
    path("admin/save/<uuid:pk>/", views.admin_save_version, name="admin_save_version"),
    path("admin/preview/<uuid:pk>/", views.admin_preview_sql, name="admin_preview_sql"),
    path("admin/preview-json/<uuid:pk>/", views.admin_preview_sql_json, name="admin_preview_sql_json"),
    path("admin/update/<uuid:pk>/", views.admin_update_request, name="admin_update_request"),
    path("admin/delete/<uuid:pk>/", views.admin_delete_request, name="admin_delete_request"),
    path("admin/ai/generate/", views.admin_ai_generate, name="admin_ai_generate"),

    # Prototype builder (is_staff)
    path("build/", views.draft_builder, name="draft_builder"),
    path("build/<uuid:pk>/", views.draft_iterate, name="draft_iterate"),
    path("build/<uuid:pk>/promote/", views.draft_promote, name="draft_promote"),
    path("build/<uuid:pk>/discard/", views.draft_discard, name="draft_discard"),
]
