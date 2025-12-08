from django.urls import path
from contracts.views.supplier_views import (
    SupplierListView,
    SupplierSearchView,
    SupplierCreateView,
    SupplierUpdateView,
    supplier_autocomplete,
)
from suppliers.views import (
    DashboardView,
    SupplierDetailView,
    supplier_search_api,
    SupplierEnrichView,
    SupplierApplyEnrichmentView,
    SupplierEnrichPageView,
    SuppliersInfoByType
)

app_name = 'suppliers'

urlpatterns = [
    path('', DashboardView.as_view(), name='supplier_dashboard'),
    path('dashboard/', DashboardView.as_view(), name='supplier_dashboard_alias'),
    path('details/', SupplierListView.as_view(), name='supplier_list'),
    path('search/', supplier_search_api, name='supplier_search_api'),
    path('info/<str:type_slug>/', SuppliersInfoByType.as_view(), name='supplier_info_by_type'),
    path('search/page/', SupplierSearchView.as_view(), name='supplier_search'),
    path('autocomplete/', supplier_autocomplete, name='supplier_autocomplete'),
    path('create/', SupplierCreateView.as_view(), name='supplier_create'),
    path('<int:pk>/', SupplierDetailView.as_view(), name='supplier_detail'),
    path('<int:pk>/detail/', SupplierDetailView.as_view(), name='supplier_detail_page'),
    path('<int:pk>/enrich/run/', SupplierEnrichPageView.as_view(), name='supplier_enrich_page'),
    path('<int:pk>/enrich/', SupplierEnrichView.as_view(), name='supplier_enrich'),
    path('<int:pk>/apply-enrichment/', SupplierApplyEnrichmentView.as_view(), name='supplier_apply_enrichment'),
    path('<int:pk>/edit/', SupplierUpdateView.as_view(), name='supplier_edit'),
]
