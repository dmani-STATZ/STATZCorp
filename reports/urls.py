"""
URL configuration for the reports app.
"""
from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    # User facing URLs
    path('', views.UserReportListView.as_view(), name='user-reports'),
    path('request/', views.ReportRequestCreateView.as_view(), name='request-report'),
    path('view/<uuid:pk>/', views.ReportViewView.as_view(), name='report-view'),
    path('change/<uuid:report_pk>/', views.ReportChangeCreateView.as_view(), name='request-change'),
    path('export/<uuid:pk>/', views.export_report, name='export-report'),
    path('generate-report/', views.ai_generate_report_view, name='ai-generate-report'),

    # Report creator URLs
    path('creator/', views.ReportCreatorListView.as_view(), name='creator-list'),
    path('creator/<uuid:pk>/', views.ReportCreatorDetailView.as_view(), name='creator-detail'),
]
