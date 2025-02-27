from django.urls import path
from . import views
from .views import (
    ContractsDashboardView,
    ContractDetailView,
    ClinDetailView,
    NsnUpdateView,
    SupplierUpdateView,
    contract_search,
    get_clin_notes,
    toggle_clin_acknowledgment
)

app_name = 'contracts'

urlpatterns = [
    path('', ContractsDashboardView.as_view(), name='contracts_dashboard'),
    path('contract/<int:pk>/', ContractDetailView.as_view(), name='contract_detail'),
    path('clin/<int:pk>/', ClinDetailView.as_view(), name='clin_detail'),
    path('nsn/<int:pk>/edit/', NsnUpdateView.as_view(), name='nsn_edit'),
    path('supplier/<int:pk>/edit/', SupplierUpdateView.as_view(), name='supplier_edit'),
    path('search/', contract_search, name='contract_search'),
    path('clin/<int:clin_id>/notes/', get_clin_notes, name='get_clin_notes'),
    path('clin/<int:clin_id>/toggle-acknowledgment/', toggle_clin_acknowledgment, name='toggle_clin_acknowledgment'),
] 