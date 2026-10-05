"""
Quotes (DIBBS Quoting) app URL configuration.

app_name MUST stay exactly 'quote': STATZWeb.middleware.LoginRequiredMiddleware
resolves the namespace and looks it up in users.AppRegistry. A mismatch makes
permission gating silently no-op.
"""
from django.urls import path

from . import research_views, views

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
    # Supplier capabilities -- the NSN / FSC lists that drive matching
    path('capabilities/', views.capabilities, name='capabilities'),
    path('capabilities/import/', views.capability_import_page, name='capability_import'),
    path('capabilities/import/preview/', views.capability_import_preview, name='capability_import_preview'),
    path('capabilities/import/commit/', views.capability_import_commit, name='capability_import_commit'),
    path('capabilities/import/<int:import_id>/undo/', views.capability_import_undo, name='capability_import_undo'),
    path('capabilities/export/', views.capability_export, name='capability_export'),
    path('capabilities/supplier/<int:supplier_id>/', views.capability_supplier, name='capability_supplier'),
    path('capabilities/supplier/<int:supplier_id>/remove/', views.capability_remove, name='capability_remove'),
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
    path('mailbox/attachments/<int:attachment_id>/view/', views.attachment_view, name='attachment_view'),
    # Phase 2 -- packhouse packaging-quote requests (drawer packaging section + message pane)
    path('packhouse/<str:sol_number>/preview/', views.packhouse_preview, name='packhouse_preview'),
    path('packhouse/<str:sol_number>/send/', views.packhouse_send, name='packhouse_send'),
    path('packhouse/reply/<int:rfq_id>/', views.packhouse_record_reply, name='packhouse_record_reply'),
    # Phase 2 -- the Quotes page: who owes us a quote, quotes on file, quotes entered by hand
    path('quotes/', views.quotes_page, name='quotes'),
    path('quotes/tray/', views.quote_tray, name='quote_tray'),
    path('quotes/sol-suppliers/', views.quote_sol_suppliers, name='quote_sol_suppliers'),
    path('quotes/rfq-close/', views.rfq_close, name='rfq_close'),
    path('quotes/remove/', views.quote_remove, name='quote_remove'),
    path('quotes/<str:sol_number>/save/', views.quote_save, name='quote_save'),
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
    path('research/', research_views.supplier_research, name='supplier_research'),
    path(
        'research/<str:cage>/export/',
        research_views.supplier_research_export,
        name='supplier_research_export',
    ),
    path(
        'research/<str:cage>/panel/<str:panel>/',
        research_views.supplier_research_panel,
        name='supplier_research_panel',
    ),
]
