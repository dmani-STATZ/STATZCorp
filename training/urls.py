from django.urls import path
from . import views

app_name = 'training'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('audit/', views.training_audit, name='training_audit'),
    path('matrix/manage/', views.manage_matrix, name='manage_matrix'),
    path('matrix/manage/<int:account_id>/', views.manage_matrix, name='manage_matrix_for_account'),
    path('requirements/', views.user_training_requirements, name='user_requirements'),
    path('mark-complete/<int:course_id>/', views.mark_complete, name='mark_complete'),
    path('upload-document/<int:matrix_id>/', views.upload_document, name='upload_document'),
    path('view-document/<int:tracker_id>/', views.view_document, name='view_document'),
    path('arctic-wolf/add/', views.add_arctic_wolf_course, name='add_arctic_wolf_course'),
    path('arctic-wolf/list/', views.arctic_wolf_course_list, name='arctic_wolf_course_list'),
    path('arctic-wolf/complete/<slug:slug>/', views.arctic_wolf_training_completion, name='arctic_wolf_training_completion'),
    path('arctic-wolf/complete/<slug:slug>/submit/', views.arctic_wolf_complete_training, name='arctic_wolf_complete_training'),
    path('my-courses/', views.user_arctic_wolf_courses, name='user_arctic_wolf_courses'), 
    path('arctic-wolf/audit/', views.arctic_wolf_audit, name='arctic_wolf_audit'),
    path('admin/cmmc-upload/', views.admin_cmmc_upload, name='admin_cmmc_upload'),
]
