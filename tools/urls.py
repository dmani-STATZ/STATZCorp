from django.urls import path
from . import views

app_name = "tools"

urlpatterns = [
    path("", views.pdf_merger, name="index"),
    path("merge/", views.merge_pdfs, name="merge_pdfs"),
    path("delete-pages/", views.delete_pages, name="delete_pages"),
    path("split/", views.split_pdf, name="split_pdf"),
]
