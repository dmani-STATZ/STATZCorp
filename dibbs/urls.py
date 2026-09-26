"""
DIBBS data app URL configuration.

app_name stays 'dibbs': STATZWeb.middleware.LoginRequiredMiddleware resolves the
namespace and looks it up in users.AppRegistry.
"""
from django.urls import path

from .views import awards
from .views import (
    awards_wins,
    competitor_supplier_intel,
    competitor_watchlist,
    competitor_watchlist_add,
    competitor_watchlist_refetch_name,
    competitor_watchlist_remove,
    dashboard,
    dibbs_notices_api,
    dibbs_notices_page,
    entity_lookup,
    import_batch_delete,
    import_fetch_dibbs,
    import_history,
    import_job_progress,
    import_step_lines,
    import_step_parse,
    import_step_solicitations,
    import_upload,
    settings_cage_add,
    settings_cage_edit,
    settings_cages,
    settings_index,
    solicitation_detail,
    solicitation_pdf_view,
)
from .views.contract_mods import acknowledge_contract_mod_view

app_name = "dibbs"

urlpatterns = [
    path("", dashboard, name="dashboard"),
    # Daily IN/BQ/AS import
    path("import/", import_upload, name="import_upload"),
    path("import/fetch-dibbs/", import_fetch_dibbs, name="import_fetch_dibbs"),
    path("import/history/", import_history, name="import_history"),
    path("import/batch/<int:batch_id>/delete/", import_batch_delete, name="import_batch_delete"),
    path("import/job/<str:job_id>/", import_job_progress, name="import_job_progress"),
    path("import/job/<str:job_id>/step/parse/", import_step_parse, name="import_step_parse"),
    path("import/job/<str:job_id>/step/solicitations/", import_step_solicitations, name="import_step_solicitations"),
    path("import/job/<str:job_id>/step/lines/", import_step_lines, name="import_step_lines"),
    # Read-only solicitation data
    path("solicitations/<str:sol_number>/pdf/", solicitation_pdf_view, name="solicitation_pdf"),
    path("solicitations/<str:sol_number>/", solicitation_detail, name="solicitation_detail"),
    # Awards list + AW file import
    path("awards/", awards.awards_list, name="awards_list"),
    path("awards/wins/", awards_wins, name="awards_wins"),
    path("awards/import/", awards.awards_import_upload, name="awards_import_upload"),
    path("awards/import/result/", awards.awards_import_result, name="awards_import_result"),
    # CAGE settings
    path("settings/", settings_index, name="settings_index"),
    path("settings/cages/", settings_cages, name="settings_cages"),
    path("settings/cages/add/", settings_cage_add, name="settings_cage_add"),
    path("settings/cages/<int:cage_id>/edit/", settings_cage_edit, name="settings_cage_edit"),
    # SAM.gov entity lookup
    path("entity/cage/<str:cage_code>/", entity_lookup, name="entity_cage_lookup"),
    # Competitors
    path("competitors/", competitor_watchlist, name="competitor_watchlist"),
    path("competitors/add/", competitor_watchlist_add, name="competitor_watchlist_add"),
    path("competitors/<int:pk>/remove/", competitor_watchlist_remove, name="competitor_watchlist_remove"),
    path(
        "competitors/<int:pk>/refetch-name/",
        competitor_watchlist_refetch_name,
        name="competitor_watchlist_refetch_name",
    ),
    path(
        "competitors/<str:cage_code>/suppliers/",
        competitor_supplier_intel,
        name="competitor_supplier_intel",
    ),
    # DIBBS notices
    path("dibbs-notices/", dibbs_notices_page, name="dibbs_notices"),
    path("dibbs-notices/api/", dibbs_notices_api, name="dibbs_notices_api"),
    # Contract modifications (acknowledged from the contracts app)
    path(
        "contract-mods/<int:pk>/acknowledge/",
        acknowledge_contract_mod_view,
        name="acknowledge_contract_mod",
    ),
]
