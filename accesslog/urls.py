from django.urls import path
from . import views

app_name = 'accesslog'

urlpatterns = [
    path('', views.visitor_log, name='visitor_log'),
    path('visitor_log/', views.visitor_log, name='visitor_log'),
    path('check-in/', views.check_in_visitor, name='check_in'),
    path('check-out/<int:visitor_id>/', views.check_out_visitor, name='check_out'),
    path('generate-report/', views.generate_report, name='generate_report'),
    path('visitor-info/', views.get_visitor_info, name='visitor_info'),
    path('staged-info/<int:staged_id>/', views.get_staged_info, name='staged_info'),
] 