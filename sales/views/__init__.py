"""
Sales app views.
"""
from sales.views.dashboard import dashboard
from sales.views.imports import import_upload
from sales.views.solicitations import (
    solicitation_list,
    solicitation_detail,
    no_bid,
    global_search,
)
from sales.views.suppliers import (
    backfill_nsn,
    supplier_list,
    supplier_detail,
    supplier_add_nsn,
    supplier_add_fsc,
    supplier_remove_nsn,
    supplier_remove_fsc,
)
from sales.views.rfq import (
    rfq_pending,
    rfq_sent,
    rfq_send_single,
    rfq_send_batch,
    rfq_center,
    rfq_center_detail,
    rfq_enter_quote,
    rfq_send_followup,
    rfq_mark_no_response,
    rfq_mark_declined,
    quote_select_for_bid,
)
from sales.views.bids import (
    bids_ready,
    bid_builder,
    bid_select_quote,
    bids_export_queue,
    bids_export_download,
)

__all__ = [
    "dashboard",
    "import_upload",
    "solicitation_list",
    "solicitation_detail",
    "no_bid",
    "global_search",
    "backfill_nsn",
    "supplier_list",
    "supplier_detail",
    "supplier_add_nsn",
    "supplier_add_fsc",
    "supplier_remove_nsn",
    "supplier_remove_fsc",
    "rfq_pending",
    "rfq_sent",
    "rfq_send_single",
    "rfq_send_batch",
    "rfq_center",
    "rfq_center_detail",
    "rfq_enter_quote",
    "rfq_send_followup",
    "rfq_mark_no_response",
    "rfq_mark_declined",
    "quote_select_for_bid",
    "bids_ready",
    "bid_builder",
    "bid_select_quote",
    "bids_export_queue",
    "bids_export_download",
]
