"""
Quotes (DIBBS Quoting) app URL configuration.

app_name MUST stay exactly 'quote': STATZWeb.middleware.LoginRequiredMiddleware
resolves the namespace and looks it up in users.AppRegistry. A mismatch makes
permission gating silently no-op.
"""
from django.urls import path

from . import views

app_name = 'quote'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    # Phase 1 -- solicitation queue + workspace
    path('solicitations/', views.solicitation_queue, name='solicitation_queue'),
    path('solicitations/data/', views.queue_data, name='queue_data'),
    path('solicitations/poll/', views.queue_poll, name='queue_poll'),
    path('solicitations/rematch/', views.rerun_matching, name='rerun_matching'),
    path('solicitations/next/', views.walk_next, name='walk_next'),
    path('solicitations/<str:sol_number>/', views.solicitation_workspace, name='solicitation_workspace'),
    path('solicitations/<str:sol_number>/match/', views.add_match, name='add_match'),
    path(
        'solicitations/<str:sol_number>/match/<int:supplier_id>/remove/',
        views.remove_match, name='remove_match',
    ),
    path('solicitations/<str:sol_number>/rfq/', views.queue_supplier_rfqs, name='queue_supplier_rfqs'),
    path('solicitations/<str:sol_number>/status/', views.set_status, name='set_status'),
    path('solicitations/<str:sol_number>/claim/', views.claim, name='claim'),
    path('suppliers/search/', views.supplier_search, name='supplier_search'),
    # Phase 1 -- RFQ dispatch
    path('rfq/', views.rfq_queue, name='rfq_queue'),
    path('rfq/send-all/', views.rfq_send_all, name='rfq_send_all'),
    path('rfq/send/<int:supplier_id>/', views.rfq_send, name='rfq_send'),
    path('rfq/<int:rfq_id>/remove/', views.rfq_remove, name='rfq_remove'),
]
