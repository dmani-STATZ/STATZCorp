from django.urls import path
from contracts.views.nsn_views import NsnUpdateView
from contracts.views.idiq_views import NsnSearchView
from products import views

app_name = 'products'

urlpatterns = [
    path('nsn/<int:pk>/edit/', NsnUpdateView.as_view(), name='nsn_edit'),
    path('nsn/search/', NsnSearchView.as_view(), name='nsn_search'),
    path('nsn/<int:pk>/', views.NsnDetailView.as_view(), name='nsn_detail'),
    path('nsn/<int:pk>/packout/', views.nsn_packout_update, name='nsn_packout_update'),
]
