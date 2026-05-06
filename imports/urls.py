from django.urls import path
from . import views

app_name = 'imports'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('new/', views.session_create, name='session_create'),
    path('<int:session_id>/', views.session_detail, name='session_detail'),
    path('<int:session_id>/commit/', views.session_commit, name='session_commit'),
    path('<int:session_id>/export/', views.session_export_csv, name='session_export'),
    path('<int:session_id>/search/', views.ajax_search_target, name='ajax_search_target'),
    path('<int:session_id>/row/<int:row_id>/match/', views.ajax_update_match, name='ajax_update_match'),
    path('<int:session_id>/row/<int:row_id>/skip/', views.ajax_skip_row, name='ajax_skip_row'),
    path('<int:session_id>/translation/', views.ajax_save_translation, name='ajax_save_translation'),
]
