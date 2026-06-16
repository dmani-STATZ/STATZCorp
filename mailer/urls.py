from django.urls import path
from . import views

app_name = 'mailer'

urlpatterns = [
    path('', views.campaign_list, name='campaign_list'),
    path('create/', views.campaign_create, name='campaign_create'),
    path('<int:pk>/', views.campaign_detail, name='campaign_detail'),
    path('<int:pk>/edit/', views.campaign_edit, name='campaign_edit'),
    path('<int:pk>/import/', views.campaign_import_recipients, name='campaign_import'),
    path('<int:pk>/audience/', views.campaign_audience, name='campaign_audience'),
    path('<int:pk>/ai/', views.campaign_generate_ai, name='campaign_generate_ai'),
    path('<int:pk>/schedule/', views.campaign_schedule, name='campaign_schedule'),
    path('recipient/<int:pk>/preview/', views.recipient_preview, name='recipient_preview'),
    path('recipient/<int:pk>/delete/', views.recipient_delete, name='recipient_delete'),
    path('recipient/<int:pk>/toggle-followup/', views.recipient_toggle_followup, name='recipient_toggle_followup'),
    
    # Follow-ups
    path('<int:pk>/followups/toggle/', views.campaign_toggle_followup, name='campaign_toggle_followup'),
    path('<int:pk>/followups/add/', views.campaign_followup_add, name='campaign_followup_add'),
    path('<int:pk>/followups/<int:followup_pk>/edit/', views.campaign_followup_edit, name='campaign_followup_edit'),
    path('<int:pk>/followups/<int:followup_pk>/delete/', views.campaign_followup_delete, name='campaign_followup_delete'),

    # Attachments
    path('<int:pk>/attachments/add/', views.campaign_attachment_add, name='campaign_attachment_add'),
    path('attachment/<int:pk>/delete/', views.campaign_attachment_delete, name='campaign_attachment_delete'),
]
