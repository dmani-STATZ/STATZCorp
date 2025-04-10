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
from django.http import HttpResponse
from . import views
from users import views as user_views

def health_check(request):
    """Simple health check endpoint to test if the server is functioning correctly."""
    return HttpResponse("OK", content_type="text/plain")

urlpatterns = [
    path("__reload__/", include("django_browser_reload.urls")),
    path('admin/', admin.site.urls),
    path('', views.landing_page, name='landing'),
    path('home/', views.index, name='index'),
    path('about/', views.about, name='about'),
    path('permission_denied/', user_views.permission_denied, name='permission_denied'),
    path('users/', include('users.urls')),
    path('inventory/', include('inventory.urls')),
    path('contracts/', include('contracts.urls')),
    path('accesslog/', include('accesslog.urls')),
    path('processing/', include('processing.urls')),
    path('health/', health_check, name='health_check'),
    # Announcement URLs
    path('announcement/add/', views.add_announcement, name='add_announcement'),
    path('announcement/delete/<int:announcement_id>/', views.delete_announcement, name='delete_announcement'),
]

# Always serve static/media files (even in production)
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
