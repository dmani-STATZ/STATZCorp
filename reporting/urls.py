from django.urls import path
from . import views

app_name = 'reporting'

urlpatterns = [
    path('', views.SavedReportListView.as_view(), name='report_list'),  # Default view
    path('create/', views.ReportCreationView.as_view(), name='create_report'),
    path('edit/<int:report_id>/', views.ReportCreationView.as_view(), name='edit_report'),
    path('view/<int:report_id>/', views.ReportDisplayView.as_view(), name='view_report'),  # New URL for viewing reports
    path('export/<int:report_id>/', views.ExportReportToExcelView.as_view(), name='export_report'),  # New export URL
    path('api/get-model-fields/', views.get_model_fields, name='get_model_fields'),
    path('api/get-table-relationships/', views.get_table_relationships, name='get_table_relationships'),
    path('api/get-field-values/', views.get_field_values, name='get_field_values'),
]
