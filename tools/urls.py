from django.urls import path
from . import views
from . import views_scan_inbox

app_name = "tools"

urlpatterns = [
    path("", views.pdf_merger, name="index"),
    path("merge/", views.merge_pdfs, name="merge_pdfs"),
    path("delete-pages/", views.delete_pages, name="delete_pages"),
    path("split/", views.split_pdf, name="split_pdf"),
    path("scan-inbox/", views_scan_inbox.scan_inbox, name="scan_inbox"),
    path("scan-inbox/items/", views_scan_inbox.scan_inbox_items, name="scan_inbox_items"),
    path("scan-inbox/pdf/", views_scan_inbox.scan_inbox_pdf, name="scan_inbox_pdf"),
    path(
        "scan-inbox/search/",
        views_scan_inbox.scan_inbox_search_view,
        name="scan_inbox_search",
    ),
    path(
        "scan-inbox/destination/",
        views_scan_inbox.scan_inbox_destination_view,
        name="scan_inbox_destination",
    ),
    path("scan-inbox/file/", views_scan_inbox.scan_inbox_file, name="scan_inbox_file"),
    path("scan-inbox/skip/", views_scan_inbox.scan_inbox_skip_view, name="scan_inbox_skip"),
]
