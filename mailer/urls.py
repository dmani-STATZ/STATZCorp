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
    path('<int:pk>/schedule/', views.campaign_schedule, name='campaign_schedule'),
    path('recipient/<int:pk>/preview/', views.recipient_preview, name='recipient_preview'),
]
