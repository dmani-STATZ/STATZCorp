"""
Quotes (DIBBS Quoting) app URL configuration.

app_name MUST stay exactly 'quote': STATZWeb.middleware.LoginRequiredMiddleware
resolves the namespace and looks it up in users.AppRegistry. A mismatch makes
permission gating silently no-op.
"""
from django.urls import path

from .views import dashboard

app_name = 'quote'

urlpatterns = [
    path('', dashboard, name='dashboard'),
]
