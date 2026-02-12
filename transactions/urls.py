from django.urls import path
from . import views

app_name = "transactions"

urlpatterns = [
    path(
        "list/<int:content_type_id>/<int:object_id>/",
        views.transaction_list,
        name="transaction_list",
    ),
    path(
        "edit/<int:content_type_id>/<int:object_id>/<str:field_name>/",
        views.transaction_edit_field,
        name="transaction_edit_field",
    ),
    path(
        "<int:pk>/",
        views.transaction_detail,
        name="transaction_detail",
    ),
    path(
        "api/field-info/",
        views.field_info_api,
        name="field_info",
    ),
]
