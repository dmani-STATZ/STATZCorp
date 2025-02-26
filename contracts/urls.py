from django.urls import path
from . import views

app_name = 'contracts'

urlpatterns = [
    path('', views.ContractsDashboardView.as_view(), name='contracts_dashboard'),
    path('contract/<int:pk>/', views.ContractDetailView.as_view(), name='contract_detail'),
    path('clin/<int:pk>/', views.ClinDetailView.as_view(), name='clin_detail'),
    path('nsn/<int:pk>/edit/', views.NsnUpdateView.as_view(), name='nsn_edit'),
    path('supplier/<int:pk>/edit/', views.SupplierUpdateView.as_view(), name='supplier_edit'),
    path('search/', views.contract_search, name='contract_search'),
] 