from django.urls import path
from . import views

app_name = 'contracts'

urlpatterns = [
    path('', views.ContractsDashboardView.as_view(), name='contracts_dashboard'),
] 