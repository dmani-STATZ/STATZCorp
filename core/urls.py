from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('api/budget/sync/', views.sync_api_budget, name='sync_api_budget'),
]
