"""
Sales (DIBBS Bidding) app URL configuration.
"""
from django.urls import path
from .views import dashboard, import_upload, solicitation_list, backfill_nsn

app_name = 'sales'

urlpatterns = [
    path('', dashboard, name='dashboard'),
    path('import/', import_upload, name='import_upload'),
    path('solicitations/', solicitation_list, name='solicitation_list'),
    path('suppliers/backfill-nsn/', backfill_nsn, name='backfill_nsn'),
]
