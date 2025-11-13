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
from users import views as user_views
from users.ms_views import MicrosoftAuthView, MicrosoftCallbackView

# --- Add these lines ---
admin.site.site_header = "STATZ Corporation Administration" # Header shown on admin pages
admin.site.site_title = "STATZ Corporation Admin Portal"             # Title in the browser tab
admin.site.index_title = "Welcome to STATZ Corporation Administration" # Title on the main admin index page
# --- End of added lines ---

def health_check(request):
    """Simple health check endpoint to test if the server is functioning correctly."""
    return HttpResponse("OK", content_type="text/plain")

def manifest_json(request):
    """Serve manifest.json with proper headers."""
    manifest_path = os.path.join(settings.STATIC_ROOT if settings.STATIC_ROOT else os.path.join(settings.BASE_DIR, 'static'), 'manifest.json')
    response = serve(request, os.path.basename(manifest_path), os.path.dirname(manifest_path))
    response['Content-Type'] = 'application/manifest+json'
    response['Access-Control-Allow-Origin'] = '*'
    response['Access-Control-Allow-Methods'] = '*'
    response['Access-Control-Allow-Headers'] = '*'
    return response

def service_worker(request):
    """Serve service worker with proper headers."""
    sw_path = os.path.join(settings.STATIC_ROOT if settings.STATIC_ROOT else os.path.join(settings.BASE_DIR, 'static'), 'sw.js')
    response = serve(request, os.path.basename(sw_path), os.path.dirname(sw_path))
    response['Content-Type'] = 'application/javascript'
    response['Service-Worker-Allowed'] = '/'
    response['Access-Control-Allow-Origin'] = '*'
    return response

def download_certificate(request):
    """Serve the SSL certificate for download"""
    # Try to find certificate in our static directory first
    cert_path = os.path.join(settings.BASE_DIR, 'static', 'certificates', 'server.crt')
    
    # Fall back to Apache directory if not found in static
    if not os.path.exists(cert_path):
        cert_path = os.path.join('C:', 'Apache24', 'conf', 'ssl', 'server.crt')
    
    try:
        response = FileResponse(open(cert_path, 'rb'),
                              as_attachment=True,
                              filename='statzutil01.crt')
        response['Content-Type'] = 'application/x-x509-ca-cert'
        return response
    except FileNotFoundError:
        return HttpResponse(
            "Certificate file not found. Please contact your system administrator.",
            status=404,
            content_type="text/plain"
        )

urlpatterns = [
    path("__reload__/", include("django_browser_reload.urls")),
    path('admin/', admin.site.urls),
    path('', views.landing, name='landing'),
    path('home/', views.index, name='index'),
    path('about/', views.about, name='about'),
    path('permission_denied/', user_views.permission_denied, name='permission_denied'),
    path('users/', include('users.urls')),
    
    # Microsoft Authentication URLs (at root level for OAuth callbacks)
    path('microsoft/login/', MicrosoftAuthView.as_view(), name='microsoft_login'),
    path('microsoft/auth-callback/', MicrosoftCallbackView.as_view(), name='microsoft_callback'),
    #path('check-auth-method/', views.check_auth_method, name='check_auth_method'),
    
    path('inventory/', include('inventory.urls')),
    path('contracts/', include('contracts.urls')),
    path('accesslog/', include('accesslog.urls')),
    path('processing/', include('processing.urls')),
    path('training/', include('training.urls')),
    path('health/', health_check, name='health_check'),
    path('reports/', include('reports.urls')),
    # Announcement URLs
    path('announcement/add/', views.add_announcement, name='add_announcement'),
    path('announcement/delete/<int:announcement_id>/', views.delete_announcement, name='delete_announcement'),

    # PWA URLs
    path('manifest.json', manifest_json, name='manifest'),
    path('sw.js', service_worker, name='service_worker'),
    path('cert-error/', TemplateView.as_view(template_name='cert_error.html'), name='cert_error'),
    path('download-cert/', download_certificate, name='download_cert'),
    
    # Health check endpoint for certificate verification
    path('api/health-check/', lambda request: JsonResponse({'status': 'ok'}), name='health_check'),
    
    # System test URLs
    path('system-test/', views.system_test, name='system_test'),
    path('api/system-test/', views.system_test_api, name='system_test_api'),
    # Secret TD Now app (tower defense)
    path('td-now/', include('td_now.urls')),
]

# Always serve static/media files (even in production)
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
