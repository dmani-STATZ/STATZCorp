from django.urls import path
from contracts.views.supplier_views import (
    SupplierListView,
    SupplierSearchView,
    SupplierDetailView as LegacySupplierDetailView,
    SupplierCreateView,
    SupplierUpdateView,
    supplier_autocomplete,
)
from suppliers.views import DashboardView, SupplierDetailView, supplier_search_api

app_name = 'suppliers'

urlpatterns = [
    path('', DashboardView.as_view(), name='supplier_dashboard'),
    path('dashboard/', DashboardView.as_view(), name='supplier_dashboard_alias'),
    path('details/', SupplierListView.as_view(), name='supplier_list'),
    path('search/', supplier_search_api, name='supplier_search_api'),
    path('search/page/', SupplierSearchView.as_view(), name='supplier_search'),
    path('autocomplete/', supplier_autocomplete, name='supplier_autocomplete'),
    path('create/', SupplierCreateView.as_view(), name='supplier_create'),
    path('<int:pk>/', LegacySupplierDetailView.as_view(), name='supplier_detail'),
    path('<int:pk>/detail/', SupplierDetailView.as_view(), name='supplier_detail_page'),
    path('<int:pk>/edit/', SupplierUpdateView.as_view(), name='supplier_edit'),
]
