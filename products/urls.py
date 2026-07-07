from django.urls import path

from contracts.views.nsn_views import NsnUpdateView
from contracts.views.idiq_views import NsnSearchView
from products import views

app_name = 'products'

urlpatterns = [
    path('', views.ObservatoryView.as_view(), name='observatory'),
    path('search/', views.portal_search, name='portal_search'),
    path('nsn/<int:pk>/edit/', NsnUpdateView.as_view(), name='nsn_edit'),
    path('nsn/search/', NsnSearchView.as_view(), name='nsn_search'),
    path('nsn/<int:pk>/', views.NsnDetailView.as_view(), name='nsn_detail'),
    path('nsn/<int:pk>/logistics/', views.nsn_logistics_update, name='nsn_logistics_update'),
    path('supplier/<int:pk>/nsns/', views.SupplierNsnView.as_view(), name='supplier_nsns'),
]
