from django.urls import path

from . import views

app_name = 'intake'

urlpatterns = [
    path('', views.DraftQueueView.as_view(), name='queue'),
    path('drafts/<int:pk>/start/', views.start_draft, name='start_draft'),
    path('drafts/<int:pk>/release/', views.release_draft, name='release_draft'),
    path('drafts/<int:pk>/delete/', views.delete_draft, name='delete_draft'),
    # Editor (Phase 2a)
    path('drafts/<int:pk>/edit/', views.edit_draft, name='edit_draft'),
    path('drafts/<int:pk>/save/', views.save_draft, name='save_draft'),
    path('drafts/<int:pk>/mark-ready/', views.mark_ready, name='mark_ready'),
    path('drafts/<int:pk>/cancel/', views.cancel_draft, name='cancel_draft'),
]
