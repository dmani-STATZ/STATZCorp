# Users Context

## 1. Purpose
The users app owns all authentication, fine-grained application access control, user-facing portal widgets, and per-user preferences that the rest of STATZCorp relies on. It brokers Microsoft Azure AD sign-in via MSAL with fallback password login for staff, gates every other Django app through the AppRegistry/AppPermission models and STATZWeb middleware, and feeds a JSON-backed portal/dashboard (sections, resources, calendar events, tasks, micro-breaks, analytics, NLP scheduling) that powers the PWA portion of the project. It also centralizes user settings, active-company selection, system messaging, and several admin/maintenance utilities so downstream apps can stay lean.

## 2. App Identity
- Django app name: users. The project installs it as users (see STATZWeb/settings.py).
- AppConfig: UsersConfig in users/apps.py registers users.signals in eady(), ensuring default settings/states are created on user creation.
- Filesystem path: <repo root>/users/.
- Role: A feature-level identity + workspace hub. It combines authentication/authorization (login views, Azure backend, AppRegistry), portal/dashboard APIs, and user experience helpers (settings, system messages, company switching) that support both end users and staff.

## 3. High-Level Responsibilities
- Orchestrate Microsoft Azure AD sign-in, token storage/refresh (zure_auth.py, ms_views.py, iews.login_view, UserOAuthToken) and a staff-friendly username/password fallback.
- Define and enforce application access control via AppRegistry/AppPermission, the admin UI (dmin.py), and the permission_denied flow consumed by STATZWeb/middleware.py.
- Power the portal/dashboard JSON APIs for sections, resources, tasks, events, NLP scheduling, micro-breaks, analytics, and announcements (iews.port*, portal_services.py, models.WorkCalendar*, models.Portal*).
- Manage user-level configuration through UserSetting/UserSettingState, the UserSettings helper, AJAX endpoints, and context processors that inject preferences, unread message counts, and the active company into templates.
- Offer staff utilities such as system messaging, SharePoint calendar import/export, company switching, and management commands that clean up or refresh the permission registry.

## 4. Key Files and What They Do
- pps.py: Defines UsersConfig and hooks the users.signals module so new users get default UserSettingState rows.
- models.py: Hosts announcements, portal sections/resources, calendar models (tasks, events, recurrences, attachments, attendance, reminders, analytics snapshots, micro-breaks), user-company memberships, AppRegistry/AppPermission, user settings, OAuth tokens, and system messages—all the data that the rest of the app surfaces.
- iews.py: The enormous request handler for login/register flows, password management, user settings pages/AJAX, system messages, portal CRUD operations, NLP scheduling, micro-break feeds, SharePoint import/export, and company switching.
- orms.py: Stylized BaseFormMixin, plus domain forms (PortalSectionForm, PortalResourceForm, WorkCalendarEventForm, WorkCalendarTaskForm, EventAttachmentForm, PasswordChange/Set, EmailLookup, OAuthPasswordSet, AdminLoginForm) that validate the concrete business rules (link/file requirements, password length/matching, etc.).
- dmin.py: Custom AppPermissionAdmin that rebuilds permissions per user, portal/admin model registrations for sections/resources, calendar objects, natural language requests, analytics/micro-breaks, and UserCompanyMembership, plus the supporting inline forms shown in staff screens.
- portal_services.py: Serializes portal data for the dashboard (serialize_section, serialize_event, etc.) and selects the visible sections/events/tasks using the same models iews expose.
- zure_auth.py: A Microsoft backend that talks to MSAL/Graph, creates users if allowed, stores/refreshes UserOAuthToken, and exposes get_valid_microsoft_token for other code that needs API access.
- ms_views.py: HTTP flows that build the MSAL authorization URL, manage callback state, log users in, set session flags, and redirect back to the PWA.
- context_processors.py: Supplies user_preferences (from UserSettings), cache_version, OpenRouter AI model defaults (suppliers.openrouter_config), unread_messages_count, and ctive_company/available_companies using contracts.Company and UserCompanyMembership.
- middleware.py: ActiveCompanyMiddleware keeps equest.active_company in sync with the session, user setting, or default contract company.
- user_settings.py: Central helper with get_setting, save_setting, and mass operations, ensuring typed conversions between UserSettingState rows and forms.
- signals.py: Adds default setting states for newly created User objects; the prior AppPermission creation signal is commented out.
- sql_fix.py: Contains a SQL Server-friendly script to create the users_appregistry table manually and populate it with AppRegistry.register_apps_from_system().
- management/commands/: Scripts such as update_app_registry, ix_appregistry, cleanup_app_permissions, check_contract_table, etc., that keep the registry/permission tables in sync or inspect legacy contracts tables.
- 	emplates/users/: UI templates for login, password resets, OAuth migration, profile, settings, system messages, and message creation, plus a ase_no layout for standalone auth screens.
- static/users/img/ms-logo.svg: Microsoft logo asset used in the login page.
- 	emplatetags/user_tags.py: get_username and dictionary access filters used by system-message templates.
- README.md: Developer-facing notes summarizing the app’s responsibilities and giving hints about the permission decorator/middleware.

## 5. Data Model / Domain Objects
- Announcement: Simple any-user post with 	itle, content, posted_by (FK to User), and posted_at; surfaced in portal_dashboard_data.
- PortalSection & PortalResource: Configurable sections with visibility/layout preferences, editor M2M ties, and JSON/effect data that restrict who can edit/see resources. The resource model enforces required fields per esource_type (ile, link, embed) in its own clean().
- WorkCalendarTask: Owner, due date, importance/energy metadata, status, and arbitrary metadata; tasks are created via portal_task_create.
- WorkCalendarEvent: Organizer-owned events with privacy flags, predicted attendance, energy/priority, NLP metadata, attachment/task relations, and clean() enforcing end_at > start_at. Attachments link back via EventAttachment.
- RecurrenceRule: One-to-one with WorkCalendarEvent, stores req/interval and weekday JSON to let _expand_recurrences feed the calendar.
- EventAttendance/EventReminder: Attendance records with status/confidence_score, and reminders (offsets/message) that staff can edit via admin.
- NaturalLanguageScheduleRequest: Logs NLP scheduling queries, diagnostics, interpreted times, and optionally the created event; statuses track the parsing lifecycle.
- CalendarAnalyticsSnapshot: Aggregated stats per user per date range (meeting_hours, ghost_meeting_rate, context_switches, suggestions) used by portal_services.latest_snapshot().
- ScheduledMicroBreak: Records auto/manual micro-breaks with insertion mode references for portal_microbreak_feed and the NLP auto-break insertion.
- UserCompanyMembership: Bridges User → contracts.Company, ensures a single is_default, and is used by middleware/context processors and contracts views/forms to show available companies.
- AppRegistry: Holds the set of registered apps with display_name/is_active, supports egister_apps_from_system(), and backs AppPermission.
- AppPermission: Links users to registry entries with has_access; get_permissions_for_user() returns a simple dict. The admin form rebuilds these rows from dynamic checkbox fields per active app.
- UserSetting & UserSettingState: Define named settings (
ame, setting_type, default_value) and the per-user value+type conversions (boolean/string/integer/json) used by UserSettings and AJAX endpoints.
- UserOAuthToken: Stores Microsoft ccess_token/efresh_token/expires_at per user; is_expired and refresh helpers keep the token valid for API calls.
- SystemMessage: Per-user notifications with priority, source metadata (source_app/model/id), ction_url, and helper methods like mark_as_read()/get_unread_count() consumed by the system_messages UI.

## 6. Request / User Flow
- **Authentication:** /users/login/ shows Microsoft + password tabs (iews.login_view). The Microsoft flow starts in ms_views.MicrosoftAuthView, runs through zure_auth.MicrosoftAuthBackend, stores tokens in UserOAuthToken, and finishes in MicrosoftCallbackView. Password login uses AdminLoginForm and uthenticate(). /users/register/ simply redirects users to Microsoft. /users/logout/ is the Django auth LogoutView.
- **Password lifecycle:** /users/password-reset/... reuses Django’s auth views; custom_password_reset reroutes OAuth-only users to /users/oauth_migration/, where EmailLookupForm captures the Microsoft email and sends the user to /users/oauth_password_set/ (OAuthPasswordSetForm) to choose a password. Logged-in users can run /users/password-change/ (PasswordChangeForm) or /users/password-set/ if they currently lack a password.
- **User settings:** /users/settings/view/ renders manage_settings.html (super user grid + AJAX) and /users/settings/ajax/* endpoints let JS read/write UserSetting values after consulting UserSettingState. /users/settings/view/ itself also shows personal settings via settings_view.html and posts to save_user_setting for quick edits.
- **Company/context:** The ActiveCompanyMiddleware (with contracts.Company, UserCompanyMembership, and UserSettings) keeps equest.active_company current. /users/switch-company/ enforces membership before writing ctive_company_id to the session and settings. Context processors expose ctive_company, vailable_companies, preferences, and unread message counts to templates.
- **Portal/dashboard APIs:** /users/portal/dashboard/ returns portal_services.build_portal_context() plus announcements. /users/portal/sections/ lists sections for all users (GET) and permits superusers to create/update (PortalSectionForm). Resources are upserted/deleted via /portal/resources/... respecting section editors and restricting file uploads to superusers. Tasks/events can be created via /portal/tasks/create/ and /portal/events/create/; the portal_event_feed endpoint returns upcoming events (expanding recurrences via _expand_recurrences). Event operations (detail/update/delete, attachments) are organizer-bound, with JSON payloads and forms ensuring validation. /portal/nlp-schedule/ parses natural language text, stores NaturalLanguageScheduleRequest, optionally auto-creates WorkCalendarEvent, and auto-inserts a ScheduledMicroBreak. /portal/microbreaks/*, /portal/events/export/csv/, /portal/events/import/sharepoint/, and /users/sharepoint-import-ui/ round out the async UX for schedule management.
- **System messaging:** /users/messages/ lists SystemMessage rows, /users/messages/create/ lets staff build notifications, /mark-read/ + /mark-all-read/ update statuses, and /unread-count/ powers the badge shown by the context processor.
- **Permissions/debug:** /users/permission-denied/ renders a reusable error page. /users/debug/permissions/ dumps all AppPermission rows for debugging. /users/test-app-name/ and /users/check-auth-method/ provide helpers for middleware diagnostics.

## 7. Templates and UI Surface Area
- Authentication UIs live in 	emplates/users/ (login.html, logout.html, egister.html, custom_password_reset.html, oauth_migration.html, oauth_password_set.html, password_* templates). login.html uses a tabbed layout with a Microsoft button (static asset static/users/img/ms-logo.svg) and a hidden password form.
- Settings UIs include manage_settings.html (AJAX-powered grid that fetches/saves settings via /settings/ajax/*), settings_view.html (simple per-user list), and profile.html (a stub rendering users/profile.html). The management page injects vanilla JS that handles input highlighting, etch calls, and dynamic setting creation.
- System messages are rendered by system_messages.html (uses user_tags.get_username to show senders, includes buttons wired to the JSON APIs for marking read). create_message.html is the form staff use to send messages.
- Portal interface is entirely JSON-driven; the templates here are only for auth/settings. The portal front-end consumes the JSON from portal_dashboard_data, portal_sections_api, portal_event_feed, etc., and the serialization helpers in portal_services.py guarantee the payload shape.
- Templatetags: 	emplatetags/user_tags.py provides helper filters used in the system message list and settings modals.
- Static assets: Minimal—currently just the Microsoft logo plus the Django admin JS reference (dmin/js/app_permissions.js) the custom permission form expects.

## 8. Admin / Staff Functionality
- dmin.py registers AppPermission with custom checkboxes per active app, PortalSection/PortalResource inlines, calendar models (tasks/events/attendance/reminders), NaturalLanguageScheduleRequest, CalendarAnalyticsSnapshot, ScheduledMicroBreak, UserCompanyMembership, Announcement, AppRegistry, and schedule-specific inlines.
- The custom admin form rebuilds AppPermission rows instead of saving the base AppPermission instance directly—the save_model override deletes old records and inserts one per checked app (AppRegistry.get_active_apps()).
- SharePoint import is gated by @user_passes_test(_is_staff) in sharepoint_import_ui, so only staff can upload XLSX files. The DebugAuthView (debug_auth.py) shows current Azure AD config for diagnostics.
- Management commands under management/commands/ let staff refresh the registry (update_app_registry, ix_appregistry), clean orphaned permissions (cleanup_permissions, cleanup_app_permissions, ix_apppermissions), and inspect legacy contracts tables (check_contract_table, check_clin_tables, migrate_notes).

## 9. Forms, Validation, and Input Handling
- BaseFormMixin/BaseModelForm apply consistent Tailwind-inspired classes to widgets across the app.
- PortalSectionForm/PortalResourceForm and the calendar/task/attachment forms wrap the models used by the portal endpoints; PortalResourceForm.clean_external_url allows non-HTTP schemes (mailto, 	el, etc.), while EventAttachmentForm.clean() enforces the required field per attachment type.
- AdminLoginForm, PasswordChangeForm, PasswordSetForm, EmailLookupForm, and OAuthPasswordSetForm encapsulate validation rules (e.g., password length, field matching, lookups). Password change/set forms require the two password fields to match and enforce an 8-character minimum.
- AJAX endpoints rely on _request_data(), json.loads, and QueryDict helpers to accept JSON or form-data, so the same views serve both browser forms and fetch requests.

## 10. Business Logic and Services
- portal_services.py centralizes portal payload construction (uild_portal_context) so views and any other consumer get the same serialized representation of sections, events, tasks, micro-breaks, analytics, and NLP requests.
- iews._parse_natural_language_request, _next_available_slot, _calculate_predicted_attendance, _auto_insert_microbreak, _import_sharepoint_xlsx_core, and _expand_recurrences contain the domain logic for NLP scheduling, conflict avoidance, auto micro-break insertion, SharePoint import, and recurrence expansion.
- UserSettings (user_settings.py) adds typed conversion helpers plus bulk getters/setters so views and context processors can rely on a single API instead of working with UserSettingState directly.
- ActiveCompanyMiddleware consults user settings/session/default companies to maintain equest.active_company, persist the selection, and expose it via the context processor.
- zure_auth.py manages the MSAL token lifecycle (acquire token by auth code, refresh, log errors, store UserOAuthToken) and keeps session flags (microsoft_auth_success) useful for the login flow.
- signals.py ensures every new User gets every setting’s default state.
- sql_fix.py and the management commands automate AppRegistry creation/cleanup in SQL Server deployments.

## 11. Integrations and Cross-App Dependencies
- contracts: UserCompanyMembership FK points to contracts.Company; the middleware/context processors (middleware.py, context_processors.py, iews.switch_company) call Company.get_default_company/Company.objects to drive company selection. contracts.views.company_views and contracts.forms import UserCompanyMembership to keep their members aligned with this app.
- STATZWeb: The custom login_required decorator from STATZWeb.decorators is reused in users/views.py, and STATZWeb/middleware.py imports AppPermission/AppRegistry to gate access across every app other than users/dmin.
- suppliers.openrouter_config: context_processors.user_preferences calls get_openrouter_model_info() so UI components know which AI model is current.
- docs/MULTI-COMPANY_Process.md (outside the app) references users.UserCompanyMembership, showing that documentation relies on this model for multi-company workflows.
- management/commands include inspectors (check_contract_table, check_clin_tables, migrate_notes) that inspect or migrate data from the contracts app, tying the user-maintenance scripts to that domain.
- Settings dependencies: zure_auth, ms_views, and iews all expect settings.AZURE_AD_CONFIG, settings.AUTHENTICATION_BACKENDS, and settings.LOGIN_REDIRECT_URL, plus settings.REQUIRE_LOGIN in middleware.
- Third-party libs: msal, equests, openpyxl, and optionally dateutil/python-dateutil (fall-back). The portal scheduler also uses Python’s json, datetime, and django.db.models.Q heavily.

## 12. URL Surface / API Surface
- Authentication: /users/register/, /users/login/, /users/logout/, /users/profile/, /users/password-reset/ + Django’s password reset/done/confirm/complete URLs, /users/custom-password-reset/, /users/oauth-migration/, /users/oauth-password-set/, /users/password-change/, /users/password-set/, and /users/check-auth-method/.
- Permissions/debug: /users/permission-denied/, /users/test-app-name/, /users/debug/permissions/, /users/debug/auth-config/.
- Company/settings: /users/switch-company/, /users/settings/view/, /users/settings/ajax/get/, /users/settings/ajax/save/, /users/settings/ajax/types/, /users/settings/view/.
- Microsoft auth: /users/microsoft/login/, /users/microsoft/auth-callback/.
- System messages: /users/messages/, /users/messages/create/, /users/messages/mark-read/<pk>/, /users/messages/mark-all-read/, /users/messages/unread-count/.
- Portal APIs: /users/portal/dashboard/, /users/portal/sections/ (GET lists, POST upserts, /sections/<id>/delete/), /users/portal/resources/ (upsert/delete), /users/portal/tasks/create/, /users/portal/events/create/, /users/portal/events/import/sharepoint/, /users/portal/events/import/ui/, /users/portal/events/export/csv/, /users/portal/events/feed/, /users/portal/events/<id>/detail/, /users/portal/events/<id>/attachments/upsert/, /users/portal/events/attachments/<id>/delete/, /users/portal/events/<id>/update/, /users/portal/events/<id>/delete/, /users/portal/nlp-schedule/, /users/portal/microbreaks/create/, /users/portal/microbreaks/feed/.
- SharePoint UI: /users/sharepoint-import-ui/ (staff-only, renders a form to call the endpoint above).

## 13. Permissions / Security Considerations
- Most views use the STATZWeb.decorators.login_required wrapper so toggling settings.REQUIRE_LOGIN flips access across the app.
- Superusers only: editing portal sections/resources marked ile, deleting sections, the SharePoint UI (@user_passes_test(_is_staff)), and the portal_sections_api POST branch.
- Event CRUD is organizer-only—portal_event_update/delete, portal_event_attachment_* ensure equest.user is the event creator. Superusers cannot edit others’ events.
- Portal resources enforce editor lists; _is_section_editor defers to editors, staff, or superusers. File-type resources are restricted to superusers for write/delete actions.
- switch_company forces membership checks via UserCompanyMembership; the middleware also validates membership before persisting the session value.
- AppPermission with AppRegistry and STATZWeb/middleware deny entry to any non-users/dmin app if the user lacks a row—or if has_access is False.
- OAuth tokens are stored in UserOAuthToken with a provider-specific unique constraint, and zure_auth._refresh_microsoft_token guards against invalid refresh tokens.
- System messages and settings pages employ CSRF-protected forms and JSON endpoints that only accept the advertised HTTP verbs.

## 14. Background Processing / Scheduled Work
- No Celery workers or scheduled jobs live in this app. The asynchronous behaviors originate from HTTP endpoints (portal APIs, NLP parsing, SharePoint import). NaturalLanguageScheduleRequest rows are created synchronously when a user calls /portal/nlp-schedule/, and the auto-scheduling logic immediately persists WorkCalendarEvent + optional micro-break.
- Management commands (update_app_registry, ix_*, cleanup_*, check_*, migrate_notes) are the only repeated maintenance tasks; they run manually or from deployment scripts.
- Signals automatically create UserSettingState rows on User.post_save, giving new users the same default preferences without extra jobs.

## 15. Testing Coverage
users/tests.py is a stub (TestCase with “Create your tests here”), so there is currently no automated test coverage tied to any of the app’s controllers, forms, APIs, or models.

## 16. Migrations / Schema Notes
- Eleven migrations exist (0001–0011). The early ones (0002–0005) iterate on AppPermission/AppRegistry, 0006 adds user settings, 0007 introduces OAuth tokens, 0008 adds system messages, 0009 adds UserCompanyMembership, and 0010/0011 create the portal/calendar models (sections, resources, tasks, events, recurrence, attachments).
- Constraints: AppPermission and AppRegistry enforce uniqueness on (user, app) and pp_name, UserSetting enforces setting names, UserCompanyMembership enforces one row per (user, company) while is_default is normalized in save(), UserOAuthToken enforces (user, provider) uniqueness.
- The portal models declare custom ordering/indexes (e.g., WorkCalendarEvent indexes on start_at and organizer, ScheduledMicroBreak ordered by start_at). The models also embed JSON blobs for metadata (PortalSection.configuration, WorkCalendarEvent.metadata, ScheduledMicroBreak.notes).

## 17. Known Gaps / Ambiguities
- sharepoint_import_ui() renders users/import_sharepoint.html, but that template does not exist in 	emplates/users/, so uploading via the UI will 404 (the API endpoint /portal/events/import/sharepoint/ still works if hit directly).
- The egister() view immediately redirects to Microsoft, so the existing egister.html template never renders unless another view uses it.
- The admin tries to include dmin/js/app_permissions.js (AppPermissionAdmin.Media), yet no such static file lives in the repo, so any custom client behavior tied to that script is undefined.
- No tests cover any of the login, portal, or settings flows, leaving behavior unverified if the login stack or portal serialization changes.

## 18. Safe Modification Guidance for Future Developers / AI Agents
- Before renaming or deleting AppRegistry/AppPermission, update STATZWeb/middleware.py, the admin form, the management commands, and sql_fix.py, and be ready to rebuild the permission rows because middleware rejects access if the registry entry is missing.
- When touching UserSetting keys, search user_settings.py, the AJAX endpoints (save_user_setting, jax_*), and manage_settings.html for string literals; the JavaScript relies on matching setting_name attributes.
- Portal payload shapes emerge from portal_services.serialize_* helpers and the JSON responses in iews.portal_*. Coordinate front-end expectations (fields like predicted_attendance, can_edit, metadata) with model changes, and keep recurrence logic in _upsert_recurrence_for_event/_expand_recurrences in sync.
- ActiveCompanyMiddleware and switch_company assume contracts.Company and UserCompanyMembership exist; migrating company logic requires updating contracts forms/views that import UserCompanyMembership.
- Azure auth touches settings.AZURE_AD_CONFIG, ms_views, zure_auth, and UserOAuthToken. Rotating secrets, altering scopes, or adding new providers should keep token-refresh logic, session flags, and the login view’s microsoft_login_url URLs aligned.
- System messaging relies on SystemMessage.get_unread_count in context_processors.unread_messages and on SystemMessage.create_message in CreateMessageView; any schema changes should preserve those helpers to keep badge counts accurate.

## 19. Quick Reference
- **Primary models:** AppRegistry/AppPermission, UserSetting/UserSettingState, UserOAuthToken, Announcement, PortalSection/PortalResource, WorkCalendarTask, WorkCalendarEvent (+ recurrence/attachments/attendance/reminders), NaturalLanguageScheduleRequest, CalendarAnalyticsSnapshot, ScheduledMicroBreak, UserCompanyMembership, SystemMessage.
- **Main URLs:** /users/login/, /users/microsoft/login/, /users/permission-denied/, /users/settings/view/, /users/portal/dashboard/, /users/portal/events/feed/, /users/messages/, /users/sharepoint-import-ui/.
- **Key templates:** 	emplates/users/login.html, manage_settings.html, settings_view.html, system_messages.html, create_message.html, and the password-reset/OAuth templates under 	emplates/users/.
- **Key dependencies:** Microsoft MSAL (msal + equests), openpyxl for SharePoint import, optional python-dateutil, Django auth/password reset stack, and suppliers.openrouter_config for AI-model defaults.
- **Risky files to inspect first:** users/views.py (large and handles virtually every user flow), portal_services.py (central serialization), users/models.py (dozens of intertwined models), zure_auth.py (token lifecycle), and dmin.py/management/commands when changing the permission registry.
