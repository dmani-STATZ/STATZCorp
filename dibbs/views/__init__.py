"""
DIBBS app views.
"""
from dibbs.views.dashboard import dashboard
from dibbs.views.imports import (
    import_upload,
    import_fetch_dibbs,
    import_history,
    import_batch_delete,
    import_job_progress,
    import_step_parse,
    import_step_solicitations,
    import_step_lines,
)
from dibbs.views.solicitations import solicitation_detail, solicitation_pdf_view
from dibbs.views.settings import (
    settings_index,
    settings_cages,
    settings_cage_add,
    settings_cage_edit,
)
from dibbs.views.entity_lookup import entity_lookup
from dibbs.views.competitor_watchlist import (
    competitor_watchlist,
    competitor_watchlist_add,
    competitor_watchlist_remove,
    competitor_watchlist_refetch_name,
)
from dibbs.views.competitor_supplier_intel import competitor_supplier_intel
from dibbs.views.dibbs_notices import dibbs_notices_api, dibbs_notices_page
from dibbs.views.awards_wins import awards_wins

__all__ = [
    "dashboard",
    "import_upload",
    "import_fetch_dibbs",
    "import_history",
    "import_batch_delete",
    "import_job_progress",
    "import_step_parse",
    "import_step_solicitations",
    "import_step_lines",
    "solicitation_detail",
    "solicitation_pdf_view",
    "settings_index",
    "settings_cages",
    "settings_cage_add",
    "settings_cage_edit",
    "entity_lookup",
    "competitor_watchlist",
    "competitor_watchlist_add",
    "competitor_watchlist_remove",
    "competitor_watchlist_refetch_name",
    "competitor_supplier_intel",
    "dibbs_notices_api",
    "dibbs_notices_page",
    "awards_wins",
]
