# AGENTS.md — `users` app

## 1. Purpose of This File

This file defines safe-edit guidance for the `users` Django app. It is written for AI coding agents and developers making changes to this app. Read `users/CONTEXT.md` first if present — this file complements it, not replaces it.

---

## 2. App Scope

The `users` app is the **central identity, authentication, permissions, and workspace hub** for the entire project. It owns:

- Microsoft Azure AD (MSAL) authentication and token management
- Per-user application access control (`AppRegistry` / `AppPermission`)
- Company-user membership bridge (`UserCompanyMembership`)
- User settings framework (`UserSetting` / `UserSettingState` / `UserSettings` helper)
- System notifications (`SystemMessage`)
- Portal dashboard APIs (sections, resources, events, tasks, micro-breaks)
- Calendar and scheduling models (events, recurrences, attendance, NLP scheduling)
- Two middleware classes (`LoginRequiredMiddleware`, `ActiveCompanyMiddleware`)
- Three global context processors (preferences, messages, active company)

It does **not** own:

- Company definition (`contracts.Company` — imported here as a FK target)
- AI model configuration (`suppliers.openrouter_config` — consumed in context processors)
- Business domain logic for sales, inventory, contracts, products, reports, etc.

This app is **core infrastructure**. Changes here can break authentication, access control, and navigation across every other app.

---

## 3. Read This Before Editing

### Before changing models
- Read `users/models.py` in full — 16+ models with JSON fields, M2M relations, computed properties
- Check `users/migrations/` for the latest migration number before creating a new one
- Search `contracts/views/company_views.py` and `contracts/forms.py` for `UserCompanyMembership` usage
- Search `users/middleware.py` for references to `AppPermission`, `AppRegistry`, and `UserCompanyMembership`
- Check `users/signals.py` — `create_user_settings` fires on every new `User` creation

### Before changing views
- Read `users/views.py` — 1600+ lines, 40+ endpoints; understand which view is involved before editing
- Check `users/urls.py` for the URL name of any view being changed
- Search the full repo for `reverse('users:<name>')` or `{% url 'users:<name>' %}` before renaming URL names
- Confirm `@login_required` or `LoginRequiredMixin` is preserved on every non-public endpoint

### Before changing forms
- Read `users/forms.py` — `PortalResourceForm` has custom `clean_external_url()` and `_post_clean()` that allow non-HTTP URI schemes (mailto:, tel:, teams:, etc.) — do not simplify these away
- Password forms (`PasswordChangeForm`, `PasswordSetForm`, `OAuthPasswordSetForm`) all enforce a minimum password length in Python — do not remove these checks

### Before changing middleware
- Read `users/middleware.py` completely — `LoginRequiredMiddleware` controls access to every app route
- Understand the public URL bypass list (`/users/login/`, `/users/microsoft/*`, etc.) before adding to it
- `ActiveCompanyMiddleware` resolves the active company from settings → session → membership → default; understand the fallback chain before touching it

### Before changing context processors
- Read `users/context_processors.py` — three processors; `active_company` processor exposes `available_companies` and `active_company` to all templates in the project
- `user_preferences` imports `suppliers.openrouter_config` — avoid creating circular imports if changing this

### Before changing admin
- Read `users/admin.py` — `AppPermissionAdmin` has a custom save flow that deletes and recreates permissions on every save
- `AppPermissionAdmin.Media` references `admin/js/app_permissions.js` which does not exist in the repo (known gap)

### Before changing auth backend
- Read `users/azure_auth.py` and `users/ms_views.py` together — they are tightly coupled
- Understand the MSAL token exchange flow before touching `authenticate()`, `MicrosoftAuthView`, or `MicrosoftCallbackView`

---

## 4. Local Architecture / Change Patterns

**Authentication:** Two paths exist — Microsoft MSAL (primary) and password (secondary). Both converge on `django.contrib.auth.login()`. The session is used to pass flags (`microsoft_auth_success`, `auth_method`) across the redirect boundary.

**Permission system:** `LoginRequiredMiddleware` resolves URL → app namespace → `AppPermission` on every request. Any change to this lookup chain can silently deny or grant access to all users.

**Portal APIs:** Most portal endpoints are JSON-only views. They return data serialized by functions in `portal_services.py`. Views orchestrate; `portal_services.py` holds serialization logic. Keep this separation.

**User settings:** All setting reads/writes should go through `UserSettings` helper (`user_settings.py`), not direct ORM queries on `UserSettingState`.

**Business logic placement:** Services go in `portal_services.py` (portal domain), `azure_auth.py` (auth domain), or `user_settings.py` (settings domain). Do not add complex logic directly into views.

**Templates:** Authentication templates are thin and use `base_no.html` (no nav). Portal UI is JavaScript-driven (JSON APIs); there are no large portal HTML templates to maintain.

**Admin:** `AppPermissionAdmin` is non-standard. It shows one row per user and uses a custom form that manages all app permissions at once. Any change to how permissions are stored must also update this admin.

**Signals:** `users/signals.py` is loaded via `apps.py ready()`. Adding or removing signal receivers must also update the `ready()` method if modules change.

---

## 5. Files That Commonly Need to Change Together

| Change | Files that move together |
|---|---|
| Add a new model | `models.py` → `migrations/` → `admin.py` → (if portal-related) `portal_services.py` → `views.py` → `urls.py` |
| Add a portal API endpoint | `views.py` → `urls.py` → `portal_services.py` (if new serialization) |
| Add a new app to the permission system | `AppRegistry` data → `update_app_registry` management command → `LoginRequiredMiddleware` bypass list (if needed) |
| Change `UserCompanyMembership` | `models.py` → `migrations/` → `middleware.py` (ActiveCompanyMiddleware) → `context_processors.py` → `contracts/views/company_views.py` → `contracts/forms.py` |
| Change `AppPermission` or `AppRegistry` | `models.py` → `migrations/` → `admin.py` (AppPermissionAdmin custom form) → `middleware.py` (LoginRequiredMiddleware) → `STATZWeb/middleware.py` (if any) |
| Change `UserSetting` or `UserSettingState` | `models.py` → `migrations/` → `user_settings.py` → `signals.py` (default state creation) → `views.py` (settings AJAX endpoints) → `context_processors.py` |
| Add new URL | `views.py` → `urls.py` |
| Change auth flow | `azure_auth.py` → `ms_views.py` → `views.py` (login_view, oauth_* views) → templates (login.html, oauth_*.html) |
| Change password forms | `forms.py` → templates (password_change.html, password_set.html, oauth_password_set.html) |
| Change `SystemMessage` | `models.py` → `migrations/` → `views.py` (message views) → `context_processors.py` (unread count) → `urls.py` → `templates/users/system_messages.html` |
| SharePoint sync config change | `sharepoint_services.py` → `STATZWeb/settings.py` → `users/CONTEXT.md` |

---

## 6. Cross-App Dependency Warnings

### This app depends on:
- `contracts.Company` — `UserCompanyMembership.company` FK; `ActiveCompanyMiddleware` imports `contracts.models.Company`
- `suppliers.openrouter_config` — `context_processors.user_preferences` imports `get_openrouter_model_info` from suppliers; any restructuring of suppliers AI config breaks this

### Other apps that depend on this app:
- **`contracts`** — imports `users` models in at least 5 files: `forms.py`, `context_processors.py`, `views/company_views.py`, `views/acknowledgment_views.py`, `views/dashboard_views.py`, `views/folder_tracking_views.py`; this is the heaviest external consumer of the `users` app
- **`reports/views.py`** — imports from `users`; verify what it imports before changing user models or URL names
- **`STATZWeb/middleware.py`** — imports `AppPermission`, `AppRegistry` from `users.models` for permission checking (separate from `users/middleware.py`)
- **`STATZWeb/views.py`** — imports from `users`; check before renaming URL names or models
- **`STATZWeb/settings.py`** — `LOGIN_URL = 'users:login'`, `AUTHENTICATION_BACKENDS` includes `users.azure_auth.MicrosoftAuthBackend`; changing the login URL name or the backend class name requires settings update
- **All apps** — every authenticated view depends on `LoginRequiredMiddleware` and `ActiveCompanyMiddleware` in `users/middleware.py`
- **All templates** — the three context processors (`user_preferences`, `unread_messages`, `active_company`) inject data into every template; exceptions in these processors break all page renders

### Inbound FK relationships (from this app to others):
- `UserCompanyMembership.company → contracts.Company` — deleting a Company record should cascade or be protected; verify `on_delete` behavior before migrations

---

## 7. Security / Permissions Rules

- **Never remove `@login_required` or `LoginRequiredMixin`** from any view except the explicitly public auth endpoints (`login_view`, `register`, Microsoft auth views, password reset views).
- **`permission_denied` view must remain accessible without login** — it is the redirect target for denied access.
- **`LoginRequiredMiddleware` bypass list is security-critical.** Any addition to the public URL list must be intentional. Wildcard bypasses (`/users/microsoft/*`) exist for a reason — understand the scope before modifying.
- **`AppPermissionAdmin.save_model()` deletes all existing permissions before recreating them.** This is intentional but dangerous if the form submission is partial. Do not change this flow without understanding the full replace semantics.
- **`UserOAuthToken` stores access tokens.** Do not add logging, exports, or admin list views that expose `access_token` or `refresh_token` fields.
- **`debug_app_permissions` and `debug_auth_config` views** expose internal state. Confirm they are protected or restricted before deploying. Currently: `debug_auth_config` is a `View` subclass — verify it has auth guards.
- **`portal_events_export_csv`** outputs event data including `is_private` events. Verify the queryset filters correctly by organizer/attendee before changing the export logic.
- **Password forms enforce an 8-character minimum in Python.** Do not remove these checks or move them to client-side only.
- **`ActiveCompanyMiddleware`** skips membership checks for superusers. This is intentional — do not accidentally apply membership restrictions to superusers.

---

## 8. Model and Schema Change Rules

- **Search repo-wide before renaming any field on `AppPermission`, `AppRegistry`, `UserCompanyMembership`, `UserSetting`, or `UserSettingState`.** These are referenced in middleware, context processors, admin, views, and other apps.
- **Before renaming `UserCompanyMembership` fields**, check `contracts/views/company_views.py`, `contracts/forms.py`, `users/middleware.py`, and `users/context_processors.py`.
- **`AppPermission.app_name` is a FK to `AppRegistry`**, not a `CharField`. Any query using `.app_name` must account for the related object traversal.
- **JSON fields** (`smart_notes`, `metadata`, `configuration`, `tags`, `byweekday`, etc.) have no enforced schema. If adding structure to these fields, document the expected keys in comments or the model docstring — do not rely on migrations to enforce shape.
- **`WorkCalendarEvent` has many nullable fields** (section, focus_reason, predicted_attendance, etc.). Adding `NOT NULL` constraints to these requires a data migration.
- **`RecurrenceRule`** is OneToOne with `WorkCalendarEvent`. Views in `portal_event_feed` expand recurrences via `_expand_recurrences()`. Changing `RecurrenceRule` fields must also update the expansion logic in `views.py`.
- **`UserOAuthToken` is OneToOne with `AUTH_USER_MODEL`** with a unique constraint on `(user, provider)`. If multi-provider support is added, the OneToOne must become a ForeignKey and the unique constraint revisited.
- **New migrations must not break `signals.py`.** The `create_user_settings` signal queries `UserSetting.objects.all()` — new settings added via migration data will be auto-assigned to existing users only if `update_or_create` patterns are used.
- **`UserCompanyMembership.is_default`** has no database constraint ensuring exactly one default per user. Logic enforcing uniqueness of `is_default=True` per user lives in the application layer; preserve this invariant in any migration or bulk data operation.

---

## 9. View / URL / Template Change Rules

- **All URL names are namespaced under `app_name = 'users'`.** External references use `users:<name>`. Search the full repo for `users:login`, `users:permission_denied`, `users:microsoft_login`, etc. before renaming.
- **`LOGIN_URL = 'users:login'` in settings.** Renaming the `login` URL name requires a settings update.
- **`permission_denied` URL name** is used as a redirect target inside `LoginRequiredMiddleware`. Renaming it requires updating `middleware.py`.
- **Portal endpoint URL names** are likely used in JavaScript. Before renaming portal URLs, search static JS files and template `<script>` blocks for the URL names.
- **Templates use `{% url 'users:...' %}`** — grep templates across the whole project before renaming URL names.
- **`sharepoint_import_ui`** renders `import_sharepoint.html`, which does not exist. Do not rely on this view being functional.
- **`register.html`** is never rendered — `register()` immediately redirects to Microsoft auth. Do not add logic to `register.html` expecting it to display.
- **Template tag `get_username`** in `users/templatetags/user_tags.py` performs a DB query per call. If used in loops, it can cause N+1 problems.
- **`base_no.html`** is the base layout for all auth-screen templates. Changes to its structure affect login, password reset, and OAuth migration flows.

---

## 10. Forms / Serializers / Input Validation Rules

- **`PortalResourceForm`** overrides `_post_clean()` to skip Django's `URLField` validation for non-HTTP URI schemes. This is intentional. Do not simplify this form without understanding that teams: and mailto: links must remain valid inputs.
- **All password-handling forms** (`PasswordChangeForm`, `PasswordSetForm`, `OAuthPasswordSetForm`) enforce matching and 8-character minimum in `clean()`. These checks must remain in Python, not just client-side.
- **`EmailLookupForm.clean_email()`** queries the DB to confirm the email exists. If user lookup logic changes (e.g., case sensitivity, multiple users per email), update this method.
- **`BaseFormMixin`** applies widget CSS classes to all form fields. If the UI framework changes, update `BaseFormMixin` — do not patch individual forms.
- **No DRF serializers exist.** Portal API endpoints return hand-constructed dicts from `portal_services.py`. Validation of portal API input happens inside views. If adding input validation, add it in the view or extract to a service function — do not introduce serializers without a plan.
- **`WorkCalendarTaskForm` and `WorkCalendarEventForm`** include JSON/metadata fields. Input from these forms is not deeply validated — treat JSON fields as trusted (staff-only) input.

---

## 11. Background Tasks / Signals / Automation Rules

- **`signals.py` — `create_user_settings`**: Fires on every `User` post-save where `created=True`. Creates default `UserSettingState` rows for all existing `UserSetting` objects. If a new `UserSetting` row is added to the database after users already exist, existing users will not get the default state — you may need a data migration or management command.
- **`apps.py ready()`**: `import users.signals` is the mechanism that connects the signal. If the signals module is renamed or moved, update `apps.py`.
- **Auto-permission creation signal** (commented out in `signals.py`): Previously auto-created `AppPermission` rows on user creation. This is disabled. Do not re-enable without reviewing the full permission lifecycle.
- **No Celery tasks.** No background job infrastructure in this app.
- **No scheduled jobs.** Micro-break insertion and NLP scheduling happen synchronously within API views (`_auto_insert_microbreak`, `_parse_natural_language_request`).
- **Management commands** — several fix/cleanup/migration commands exist (`cleanup_app_permissions.py`, `fix_apppermissions.py`, `fix_appregistry.py`). These suggest a history of schema churn in the permission models. Review these before making further changes to `AppPermission` or `AppRegistry`.

---

## 12. Testing and Verification Expectations

**Current state:** `users/tests.py` is a stub with no actual tests. No meaningful automated coverage exists for this app.

**Practical verification after edits:**

- **Auth flow:** Log in via Microsoft and via username/password. Confirm redirect to `LOGIN_REDIRECT_URL`. Confirm session flags are set.
- **Permission middleware:** Log in as a user with no `AppPermission` rows and attempt to access a protected app URL. Confirm redirect to `permission_denied`.
- **Company switching:** Use `switch_company` endpoint. Confirm `active_company` in context changes on next page load.
- **User settings AJAX:** Open `/users/settings/view/`, change a setting, verify AJAX save succeeds and persists.
- **System messages:** Create a message via `/users/messages/create/`. Confirm unread count badge appears. Mark as read and confirm count updates.
- **Portal dashboard API:** Authenticated GET to `/users/portal/dashboard/` returns 200 with JSON body.
- **Admin permissions form:** Open `/admin/users/apppermission/`, edit a user's permissions, save, and verify the DB rows match.
- **New user creation:** Create a new user; verify `UserSettingState` default rows are created via `create_user_settings` signal.
- **Context processors:** Load any page after editing context processors; confirm no `AttributeError` or `ImportError` on `request.active_company`, unread count, or user preferences.

---

## 13. Known Footguns

1. **`LoginRequiredMiddleware` controls all app access.** A typo in the public URL bypass list can either lock out all users or open protected routes. Test auth state after any middleware change.

2. **`AppPermissionAdmin.save_model()` replaces all permissions.** If the admin form is submitted with a subset of apps checked (e.g., a stale form), all unchecked apps lose access. This is the intended behavior but can surprise editors.

3. **`admin/js/app_permissions.js` is missing.** The admin JS for `AppPermissionAdmin` does not exist in the repo. The admin page may partially malfunction. Do not assume the admin JS is working.

4. **`sharepoint_import_ui` renders a template that does not exist.** This view will return a `TemplateDoesNotExist` error. Do not assume it is functional.

5. **`context_processors.py` imports from `suppliers`.** If the suppliers app is restructured or `openrouter_config` is renamed, all page renders will fail with an `ImportError`.

6. **`_expand_recurrences()` in `views.py`** creates synthetic event dicts; they are not model instances. Any code consuming `portal_event_feed` output that expects ORM methods on event objects will break.

7. **`UserCompanyMembership.is_default` uniqueness is not enforced at the DB level.** Application code assumes one default per user. Bulk inserts or direct DB edits can violate this assumption silently.

8. **JSON fields across multiple models have no schema enforcement.** Code that reads these fields without defensive `.get()` calls will raise `KeyError` if the stored shape doesn't match expectations.

9. **`portal_nlp_schedule` is a synchronous NLP parsing endpoint.** It calls `_parse_natural_language_request()` which may do expensive string processing. This is not backgrounded — under load, it will block.

10. **`create_user_settings` signal only fires on user creation.** Adding a new `UserSetting` to the database will not automatically create `UserSettingState` for existing users. Deployments adding new settings need a data migration or management command.

11. **`UserOAuthToken.is_expired` uses `timezone.now()`.** If the system clock is wrong or tokens have unusual expiry times, token refresh logic can misbehave silently.

12. **`STATZWeb/middleware.py` also imports `AppPermission` and `AppRegistry`** — separate from `users/middleware.py`. Two middleware files manage related concerns; a change to the permission model must be reflected in both.

13. **`sharepoint_services.get_graph_service_token()`** uses the client credentials flow against `login.microsoftonline.us` — not the user OAuth flow. Do not mix these two token flows. Do not pass a service token to `UserOAuthToken` or `azure_auth` helpers. The calendar list and the document library are on different SharePoint sites. Always use `SHAREPOINT_CALENDAR_SITE_ID` for calendar Graph calls and `SHAREPOINT_SITE_ID` for document library Graph calls. Never substitute one for the other.

14. **SharePoint calendar timezone correction:** `sharepoint_services._correct_sharepoint_datetime()` is required for every Graph start/end datetime entering `WorkCalendarEvent` from `sync_sharepoint_calendar()`. Do not bypass it or parse Graph UTC values directly for those fields — the SharePoint site is Pacific-configured while users type Central, so raw Graph UTC is offset-corrupted. Behavior is driven by env var `SHAREPOINT_SOURCE_TIMEZONE`.

15. **Calendar sync triggers**: Do NOT re-add auto-sync on index page load — the scheduled WebJob owns recurring sync. The manual "Sync SP" button is intentionally superuser-gated (both in the template and at the view level). Re-exposing it to all users would double-bill Graph API calls against the already-running WebJob.

---

## 14. Safe Change Workflow

1. **Read `users/CONTEXT.md`** for high-level orientation.
2. **Identify the exact file(s)** involved in your change — don't guess from the directory listing.
3. **Read the full relevant file(s)** before editing; `views.py` is 1600+ lines and `models.py` has 16+ models.
4. **Search repo-wide** for any URL names, model names, or function names you're changing:
   - `grep -r "users:<url_name>"` across templates and Python files
   - `grep -r "from users.models import"` before changing model field names
   - `grep -r "from users.middleware import"` or references in `STATZWeb/`
5. **Make minimal, scoped changes.** Avoid refactoring adjacent code unless it is directly related to the task.
6. **Update all coupled files together** (see Section 5).
7. **Verify via the manual checklist** in Section 12.
8. **Check `STATZWeb/middleware.py`** if you changed anything in `AppPermission` or `AppRegistry`.
9. **Check `contracts/`** if you changed `UserCompanyMembership`.
10. **Check `context_processors.py`** if you changed `SystemMessage`, `UserSetting`, or `UserCompanyMembership`.

---

## 15. Quick Reference

### Primary files to inspect first
- `users/models.py` — all data models
- `users/middleware.py` — `LoginRequiredMiddleware`, `ActiveCompanyMiddleware`
- `users/views.py` — 40+ endpoints
- `users/urls.py` — all URL names
- `users/azure_auth.py` + `users/ms_views.py` — Microsoft auth
- `users/portal_services.py` — portal serialization logic
- `users/context_processors.py` — global template context

### Main coupled areas
- Models ↔ migrations ↔ admin ↔ middleware ↔ context processors
- Auth backend ↔ MS views ↔ login templates ↔ settings.py
- AppPermission ↔ AppRegistry ↔ LoginRequiredMiddleware ↔ AppPermissionAdmin
- UserCompanyMembership ↔ ActiveCompanyMiddleware ↔ contracts/views/company_views.py

### Main cross-app dependencies
- **contracts** — imports `UserCompanyMembership`
- **suppliers** — `context_processors.py` imports AI model config from suppliers
- **STATZWeb** — settings reference `users:login`; separate middleware imports `AppPermission`/`AppRegistry`

### Main security-sensitive areas
- `middleware.py` — all access control
- `azure_auth.py` — token handling
- `AppPermissionAdmin` — permission management
- `UserOAuthToken` — token storage (never log or export token fields)
- Password forms — minimum length enforcement in Python

### Riskiest edit types
- Changing the public URL bypass list in `LoginRequiredMiddleware`
- Renaming `AppPermission`, `AppRegistry`, or `UserCompanyMembership` fields
- Changing `AppPermissionAdmin.save_model()` logic
- Modifying context processors (breaks all templates on exception)
- Renaming the `users:login`, `users:permission_denied`, or `users:microsoft_callback` URL names
- Adding `NOT NULL` constraints to nullable JSON or optional fields without a data migration
