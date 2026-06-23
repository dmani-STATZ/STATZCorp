from django.urls import path

from . import views

app_name = 'intake'

urlpatterns = [
    path('', views.DraftQueueView.as_view(), name='queue'),
    path('drafts/<int:pk>/start/', views.start_draft, name='start_draft'),
    path('drafts/<int:pk>/release/', views.release_draft, name='release_draft'),
    path('drafts/<int:pk>/delete/', views.delete_draft, name='delete_draft'),
    path('drafts/<int:pk>/update-company/', views.update_draft_company, name='update_draft_company'),
    # Editor (Phase 2a)
    path('drafts/<int:pk>/edit/', views.edit_draft, name='edit_draft'),
    path('drafts/<int:pk>/save/', views.save_draft, name='save_draft'),
    path('drafts/<int:pk>/autosave/', views.autosave_draft, name='autosave_draft'),
    path('drafts/<int:pk>/remove-packaging/', views.remove_packaging_api, name='remove_packaging'),
    path('drafts/<int:pk>/mark-ready/', views.mark_ready, name='mark_ready'),
    path('drafts/<int:pk>/cancel/', views.cancel_draft, name='cancel_draft'),
    # Phase 2b: unified buyer/idiq/nsn/supplier matcher
    path('drafts/<int:pk>/match/', views.match_endpoint, name='match'),
    # Phase 3a: shred draft into canonical contracts.*
    path('drafts/<int:pk>/finalize/', views.finalize_draft_view, name='finalize_draft'),
    path('drafts/<int:pk>/finalize-direct/', views.finalize_direct_view, name='finalize_direct'),
    path('email-compose/', views.email_compose_page, name='email_compose'),
    path('send-email/', views.send_contract_email, name='send_contract_email'),
    # Phase 3c: PDF drag-and-drop ingestion
    path('upload/', views.upload_pdfs, name='upload_pdfs'),
    # SharePoint scan API
    path('api/scan-sharepoint/', views.scan_sharepoint_drafts, name='scan_sharepoint_drafts'),
    path('drafts/<int:pk>/fetch-dibbs-pdf/', views.fetch_dibbs_pdf, name='fetch_dibbs_pdf'),
]
