from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('search/', views.global_search, name='global_search'),
    path('api/budget/sync/', views.sync_api_budget, name='sync_api_budget'),
]
