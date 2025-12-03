from django.urls import path
from contracts.views.nsn_views import NsnUpdateView
from contracts.views.idiq_views import NsnSearchView

app_name = 'products'

urlpatterns = [
    path('nsn/<int:pk>/edit/', NsnUpdateView.as_view(), name='nsn_edit'),
    path('nsn/search/', NsnSearchView.as_view(), name='nsn_search'),
]
