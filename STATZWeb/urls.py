"""
URL configuration for STATZWeb project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse, FileResponse, JsonResponse
from django.views.static import serve
from django.views.generic import TemplateView
import os
from . import views
from STATZWeb.version_utils import get_version_info
from users import views as user_views
from users.ms_views import MicrosoftAuthView, MicrosoftCallbackView
from core import views as core_views

# --- Add these lines ---
admin.site.site_header = (
    "STATZ Corporation Administration"  # Header shown on admin pages
)
admin.site.site_title = "STATZ Corporation Admin Portal"  # Title in the browser tab
admin.site.index_title = (
    "Welcome to STATZ Corporation Administration"  # Title on the main admin index page
)
# --- End of added lines ---


def manifest_json(request):
    """Serve manifest.json with proper headers."""
    manifest_path = os.path.join(
        (
            settings.STATIC_ROOT
            if settings.STATIC_ROOT
            else os.path.join(settings.BASE_DIR, "static")
        ),
        "manifest.json",
    )
    response = serve(
        request, os.path.basename(manifest_path), os.path.dirname(manifest_path)
    )
    response["Content-Type"] = "application/manifest+json"
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = "*"
    response["Access-Control-Allow-Headers"] = "*"
    return response


def service_worker(request):
    """Serve service worker as a Django template so cache_version is injected."""
    from django.template.loader import render_to_string as render_template

    version_info = get_version_info()
    short_hash = version_info.get("short_hash", "")
    cache_version = os.environ.get("WEBSITE_DEPLOYMENT_ID", "")
    if not cache_version and short_hash and short_hash != "unknown":
        cache_version = short_hash
    cache_version = cache_version or "1"
    cache_version = (
        cache_version.strip().replace("'", "").replace('"', "").replace(" ", "-")
    )

    content = render_template("sw.js", {"cache_version": cache_version})
    response = HttpResponse(content, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    response["Access-Control-Allow-Origin"] = "*"
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response["Pragma"] = "no-cache"
    return response


def download_certificate(request):
    """Serve the SSL certificate for download"""
    # Try to find certificate in our static directory first
    cert_path = os.path.join(settings.BASE_DIR, "static", "certificates", "server.crt")

    # Fall back to Apache directory if not found in static
    if not os.path.exists(cert_path):
        cert_path = os.path.join("C:", "Apache24", "conf", "ssl", "server.crt")

    try:
        response = FileResponse(
            open(cert_path, "rb"), as_attachment=True, filename="statzutil01.crt"
        )
        response["Content-Type"] = "application/x-x509-ca-cert"
        return response
    except FileNotFoundError:
        return HttpResponse(
            "Certificate file not found. Please contact your system administrator.",
            status=404,
            content_type="text/plain",
        )


urlpatterns = [
    path("__reload__/", include("django_browser_reload.urls")),
    path("admin/", admin.site.urls),
    path("", views.landing, name="landing"),
    path("home/", views.index, name="index"),
    path("about/", views.about, name="about"),
    path("permission_denied/", user_views.permission_denied, name="permission_denied"),
    path("users/", include("users.urls")),
    path("whats-new/", user_views.whats_new, name="whats_new"),
    # Microsoft Authentication URLs (at root level for OAuth callbacks)
    path("microsoft/login/", MicrosoftAuthView.as_view(), name="microsoft_login"),
    path(
        "microsoft/auth-callback/",
        MicrosoftCallbackView.as_view(),
        name="microsoft_callback",
    ),
    # path('check-auth-method/', views.check_auth_method, name='check_auth_method'),
    path("inventory/", include("inventory.urls")),
    path("contracts/", include("contracts.urls")),
    path("sales/", include("sales.urls")),
    path("suppliers/", include("suppliers.urls")),
    path("products/", include("products.urls")),
    path("accesslog/", include("accesslog.urls")),
    path("processing/", include("processing.urls")),
    path("intake/", include("intake.urls")),
    path("training/", include("training.urls")),
    path("health/", core_views.health_plain, name="health_check"),
    # Azure App Service: set Health check path to /api/azure-health/
    path("api/azure-health/", core_views.azure_health, name="azure_health"),
    path("reports/", include("reports.urls")),
    path("transactions/", include("transactions.urls")),
    path("core/", include("core.urls")),
    # Announcement URLs
    path("announcement/add/", views.add_announcement, name="add_announcement"),
    path(
        "announcement/delete/<int:announcement_id>/",
        views.delete_announcement,
        name="delete_announcement",
    ),
    # PWA URLs
    path("manifest.json", manifest_json, name="manifest"),
    path("sw.js", service_worker, name="service_worker"),
    path(
        "cert-error/",
        TemplateView.as_view(template_name="cert_error.html"),
        name="cert_error",
    ),
    path("download-cert/", download_certificate, name="download_cert"),
    # Health check endpoint for certificate verification
    path(
        "api/health-check/",
        lambda request: JsonResponse({"status": "ok"}),
        name="api_health_check",
    ),
    path(
        "api/calendar/sharepoint-sync/",
        views.sharepoint_sync_view,
        name="sharepoint_sync",
    ),
    # System test URLs
    path("system-test/", views.system_test, name="system_test"),
    path("api/system-test/", views.system_test_api, name="system_test_api"),
    path("tools/", include("tools.urls")),
    path("imports/", include("imports.urls", namespace="imports")),
]

# Always serve static/media files (even in production)
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
