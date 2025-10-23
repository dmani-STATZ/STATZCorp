Milestone 1: Create the company model, user assignments, and migrations that tag contracts/processing data (Issues 1 & 4 for core tables). Deploying this behind a feature flag lets you verify data integrity.
-Issue 1 – No data model for multi-company ownership
Currently contracts.models.Contract, processing.models.ProcessContract, and the related queue/CLIN tables have no way to associate records with a company, nor can users be scoped to a set of companies. We need a first-class company model plus user-to-company assignments so that contracts, processing work, reminders, notes, etc. can all be partitioned per company.


Milestone 2: Build the active-company selector and wire it into the navigation (Issue 2). During this phase you can still limit access to superusers for testing.
-Issue 2 – No mechanism for selecting an active company per request
Views assume a single global dataset. We need a request-scoped “active company” derived from session state, defaulted from membership, and surfaced to templates.


Milestone 3: Update the rest of the views/forms/APIs to respect request.active_company (Issue 3). This is where comprehensive regression testing matters.
-Issue 3 – Queries, forms, and APIs ignore company scope
All read/write paths must filter by company to prevent data leakage. This affects dashboards (contracts/views/dashboard_views.py), management screens (contracts/views/contract_views.py, contracts/views/folder_tracking_views.py), processing pipelines (processing/views/processing_views.py, processing/views/api_views.py), and forms.


Milestone 4: Finish tagging ancillary tables (reminders, notes, etc.) and update documentation/tests (remaining pieces of Issues 1 & 4).
-Issue 4 – Migration and verification of existing data
Transitioning existing single-company data requires careful backfill, regression checks, and documentation.