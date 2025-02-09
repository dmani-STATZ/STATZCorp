from django.urls import path
from . import views

urlpatterns = [
    path('', views.visitor_log, name='visitor_log'),
    path('check-in/', views.check_in_visitor, name='check_in'),
    path('check-out/<int:visitor_id>/', views.check_out_visitor, name='check_out'),
    path('generate-report/', views.generate_report, name='generate_report'),
    path('visitor-info/', views.get_visitor_info, name='visitor_info'),
] 