from django.urls import path
from contracts.views.supplier_views import (
    SupplierListView,
    SupplierSearchView,
    SupplierDetailView,
    SupplierCreateView,
    SupplierUpdateView,
    supplier_autocomplete,
)

app_name = 'suppliers'

urlpatterns = [
    path('', SupplierListView.as_view(), name='supplier_list'),
    path('search/', SupplierSearchView.as_view(), name='supplier_search'),
    path('autocomplete/', supplier_autocomplete, name='supplier_autocomplete'),
    path('create/', SupplierCreateView.as_view(), name='supplier_create'),
    path('<int:pk>/', SupplierDetailView.as_view(), name='supplier_detail'),
    path('<int:pk>/edit/', SupplierUpdateView.as_view(), name='supplier_edit'),
]
