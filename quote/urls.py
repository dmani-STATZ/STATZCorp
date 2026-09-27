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
    # Phase 2 -- quotes@ mailbox + quote entry
    path('mailbox/', views.mailbox_page, name='mailbox'),
    path('mailbox/sync/', views.mailbox_sync, name='mailbox_sync'),
    path('mailbox/solicitations/', views.solicitation_search, name='mailbox_sol_search'),
    path('mailbox/<int:email_id>/', views.email_detail, name='email_detail'),
    path('mailbox/<int:email_id>/link/', views.email_link, name='email_link'),
    path('mailbox/<int:email_id>/unlink/', views.email_unlink, name='email_unlink'),
    path('mailbox/<int:email_id>/supplier/', views.email_set_supplier, name='email_set_supplier'),
    path('mailbox/<int:email_id>/quote/', views.save_quote, name='save_quote'),
    path('mailbox/attachments/<int:attachment_id>/', views.attachment_download, name='attachment_download'),
    # Phase 3 -- bid staging + BQ export
    path('bids/', views.bid_board, name='bid_board'),
    path('bids/export/', views.bid_export, name='bid_export'),
    path('bids/export/<str:filename>/', views.bid_reexport, name='bid_reexport'),
    path('bids/export/<str:filename>/reopen/', views.bid_reopen_export, name='bid_reopen_export'),
    path('bids/<str:sol_number>/', views.bid_builder, name='bid_builder'),
    path('bids/<str:sol_number>/compare/', views.compare_quotes, name='compare_quotes'),
    path('quotes/<int:quote_id>/select/', views.select_quote, name='select_quote'),
    # Phase 4 -- Our Bids (post-award intelligence)
    path('our-bids/', views.our_bids, name='our_bids'),
    path('our-bids/reconcile/', views.reconcile_now, name='reconcile_now'),
    path('our-bids/<int:outcome_id>/', views.outcome_detail, name='outcome_detail'),
    # Phase 1 -- RFQ dispatch
    path('rfq/', views.rfq_queue, name='rfq_queue'),
    path('rfq/send-all/', views.rfq_send_all, name='rfq_send_all'),
    path('rfq/send/<int:supplier_id>/', views.rfq_send, name='rfq_send'),
    path('rfq/<int:rfq_id>/remove/', views.rfq_remove, name='rfq_remove'),
]
