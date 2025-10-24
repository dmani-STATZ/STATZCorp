Milestone 1: Create the company model, user assignments, and migrations that tag contracts/processing data (Issues 1 & 4 for core tables). Deploying this behind a feature flag lets you verify data integrity.
-Issue 1 – No data model for multi-company ownership
Currently contracts.models.Contract, processing.models.ProcessContract, and the related queue/CLIN tables have no way to associate records with a company, nor can users be scoped to a set of companies. We need a first-class company model plus user-to-company assignments so that contracts, processing work, reminders, notes, etc. can all be partitioned per company.


Milestone 2: Build the active-company selector and wire it into the navigation (Issue 2). During this phase you can still limit access to superusers for testing.
-Issue 2 – No mechanism for selecting an active company per request
Views assume a single global dataset. We need a request-scoped “active company” derived from session state, defaulted from membership, and surfaced to templates.
    Implementation:
        All set — I implemented Milestone 2.

            What I changed:
            Middleware: Added users/middleware.py to set request.active_company per request based on session, default membership, or global default. Enforces membership unless superuser.
            Context: Extended users/context_processors.py to provide active_company and available_companies to templates.
            Switch View/URL: Added users.views.switch_company (superuser-only, POST) and wired it at users/switch-company/ (name users:switch_company).
            Settings: Inserted users.middleware.ActiveCompanyMiddleware into MIDDLEWARE and users.context_processors.active_company into template context_processors in STATZWeb/settings.py.
            UI: Added a company selector dropdown in the header of templates/base_template.html (visible to superusers only). It submits on change and returns to the current page.

            How it works:
            The middleware sets request.active_company for authenticated users each request.
            Superusers can switch the active company from the header dropdown; this stores the selection in session.
            Templates receive active_company and available_companies for display (non-superusers won’t see the selector UI).
            Files touched

            users/middleware.py:1
            users/context_processors.py:1
            users/views.py:1
            users/urls.py:1
            STATZWeb/settings.py:1
            templates/base_template.html:1




Milestone 3: Update the rest of the views/forms/APIs to respect request.active_company (Issue 3). This is where comprehensive regression testing matters.
-Issue 3 – Queries, forms, and APIs ignore company scope
All read/write paths must filter by company to prevent data leakage. This affects dashboards (contracts/views/dashboard_views.py), management screens (contracts/views/contract_views.py, contracts/views/folder_tracking_views.py), processing pipelines (processing/views/processing_views.py, processing/views/api_views.py), and forms.


Milestone 4: Finish tagging ancillary tables (reminders, notes, etc.) and update documentation/tests (remaining pieces of Issues 1 & 4).
-Issue 4 – Migration and verification of existing data
Transitioning existing single-company data requires careful backfill, regression checks, and documentation.

### Deployment Playbook: Backfilling Existing Data Before Adding More Companies

Follow these steps when promoting the multi-company work into an environment that already contains production contracts. The goal is to ensure every legacy record is tied to the initial company and every active user has a membership before a second company is introduced.

1. **Verify the default company row exists.**
   ```python
   from contracts.models import Company

   company, created = Company.objects.get_or_create(
       slug="company-a",
       defaults={"name": "Company A", "is_active": True},
   )
   print(company, created)
   ```
   *If `created` is `True`, this environment has just been initialized; otherwise the row is already present.*

2. **Backfill core contract tables.**
   ```python
   from contracts.models import Company, Contract, Clin
   from processing.models import ProcessContract, ProcessClin, QueueContract, QueueClin

   target_company = Company.objects.get(slug="company-a")

   Contract.objects.filter(company__isnull=True).update(company=target_company)
   Clin.objects.filter(company__isnull=True).update(company=target_company)

   ProcessContract.objects.filter(company__isnull=True).update(company=target_company)
   ProcessClin.objects.filter(company__isnull=True).update(company=target_company)
   QueueContract.objects.filter(company__isnull=True).update(company=target_company)
   QueueClin.objects.filter(company__isnull=True).update(company=target_company)
   ```

3. **Backfill the ancillary tables added in Milestone 4.**
   ```python
   from contracts.models import Company, Note, Reminder

   target_company = Company.objects.get(slug="company-a")

   Note.objects.filter(company__isnull=True).update(company=target_company)
   Reminder.objects.filter(company__isnull=True).update(company=target_company)
   ```

4. **Seed user memberships.**
   ```python
   from django.contrib.auth import get_user_model
   from contracts.models import Company
   from users.models import UserCompanyMembership

   target_company = Company.objects.get(slug="company-a")
   User = get_user_model()

   for user in User.objects.filter(is_active=True):
       membership, created = UserCompanyMembership.objects.get_or_create(
           user=user,
           company=target_company,
           defaults={"is_default": True},
       )
       if not membership.is_default:
           membership.is_default = True
           membership.save(update_fields=["is_default"])
   ```

5. **Smoke-test the active-company selector.**
   Log in as a superuser. The header badge should read something like “Contracts - Company A,” and the company selector should list only Company A until additional companies are added.

6. **Capture baseline metrics.**
   Export quick reports (counts of contracts, CLINs, reminders) so you can validate post-migration numbers after the backfill.

7. **Only then create the next company.**
   Use the Contracts → Companies screen (superuser only) to add a new company, upload branding, and grant memberships. Once a second company exists, users will see it in the selector according to their memberships.

Keep this checklist with the deployment runbook so every environment (QA, staging, production) follows the exact same sequence before multi-company data is active.
