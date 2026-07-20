from django.urls import path

from . import views

app_name = "supplier_portal"

urlpatterns = [
    path(
        "send-email/",
        views.SendEmailView.as_view(),
        name="send_email",
    ),
    path(
        "suppliers/<str:cage_code>/verify/",
        views.SupplierVerifyView.as_view(),
        name="verify",
    ),
    path(
        "suppliers/<str:cage_code>/",
        views.SupplierProfileView.as_view(),
        name="profile",
    ),
    path(
        "suppliers/<str:cage_code>/contacts/",
        views.ContactCollectionView.as_view(),
        name="contacts",
    ),
    path(
        "suppliers/<str:cage_code>/contacts/<int:contact_id>/",
        views.ContactDetailView.as_view(),
        name="contact_detail",
    ),
    path(
        "suppliers/<str:cage_code>/documents/",
        views.DocumentUploadView.as_view(),
        name="documents",
    ),
    path(
        "suppliers/<str:cage_code>/documents/<int:document_id>/download/",
        views.DocumentDownloadView.as_view(),
        name="document_download",
    ),
    path(
        "suppliers/<str:cage_code>/documents/<int:document_id>/file/",
        views.DocumentFileServeView.as_view(),
        name="document_file",
    ),
]
