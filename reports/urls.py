"""
URL configuration for the reports app.
"""
from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    path('nli/', views.NLQueryView.as_view(), name='nli_query'),
    path('nli/training/', views.NLITrainingView.as_view(), name='nli_training'),
    path('nli/training/queries/', views.NLITrainingAPIView.as_view(), {'action': 'queries'}, name='nli_training_queries'),
    path('nli/training/stats/', views.NLITrainingAPIView.as_view(), {'action': 'stats'}, name='nli_training_stats'),
    path('nli/training/query/<int:query_id>/', views.NLITrainingAPIView.as_view(), {'action': 'query'}, name='nli_training_query'),
    path('nli/training/query/<int:query_id>/update/', views.NLITrainingAPIView.as_view(), {'action': 'update'}, name='nli_training_query_update'),
    path('nli/training/query/<int:query_id>/mark-correct/', views.NLITrainingAPIView.as_view(), {'action': 'mark-correct'}, name='nli_training_query_mark_correct'),
    path('nli/training/query/<int:query_id>/verify-sql/', 
         views.NLITrainingAPIView.as_view(), 
         {'action': 'verify-sql'}, 
         name='nli_training_query_verify_sql'),
    path('nli/training/delete-all/', views.NLITrainingAPIView.as_view(), {'action': 'delete-all'}, name='nli_training_delete_all'),
]
