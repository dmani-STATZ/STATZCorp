# Accesslog Context

## 1. Purpose
The ccesslog app records on-site visitor check-ins and check-outs, stages planned visitors, and produces an exportable PDF for any month. It exposes the Visitor and Staged models through a small UI at /accesslog/ so staff can track who is on-site without digging into sales, inventory, or processing apps.

## 2. App Identity
- Django app name: ccesslog (app config AccesslogConfig, verbose name 'Visitors Log').
- Filesystem path: ccesslog/ alongside the other Django apps at the project root.
- Role: support/operations app that focuses on facility visitor logging rather than being a core CRM, reporting, or transaction consumer.

## 3. High-Level Responsibilities
- Persist visitor records (Visitor) with date, timestamps, company/reason details, citizenship flag, and departed status.
- Maintain a staging area (Staged) to queue visitor info before check-in so repeat visitors can be reused.
- Provide UI views for listing visitors, checking them in or out, and generating monthly reports.
- Serve JSON helpers so the check-in form can auto-fill fields from staged or historical visitors.
- Export a ReportLab-powered PDF per month for security or compliance staff to download.

## 4. Key Files and What They Do
| File | Purpose |
| --- | --- |
| models.py | Defines Visitor and Staged plus ordering and human-readable string representations. |
| orms.py | Supplies the custom VisitorHistoryField, the VisitorCheckInForm widgets/labels, and MonthYearForm that queries TruncMonth to populate the report selector. |
| iews.py | Implements visitor list, check-in/out, PDF export, and JSON helpers with conditional_login_required; PDF rendering uses ReportLab functions imported at the top. |
| urls.py | Declares the ccesslog namespace routes: visitor log, check-in/out, report generation, and AJAX info endpoints. |
| dmin.py | Registers Visitor and Staged with the default admin site. |
| 	emplates/accesslog/visitor_log.html | Presents the visitor log table, check-in link, report form, and per-visitor check-out buttons with Tailwind-style styling. |
| 	emplates/accesslog/check_in.html | Renders the check-in form, previous visitor dropdown, action buttons, hidden inputs, and inline JavaScript that fetches visitor or staged info. |
| migrations/0001-0005_*.py | Tracks schema evolution from the initial Visitor model to the current datetime fields and the Staged model with citizen/date metadata. |

## 5. Data Model / Domain Objects
- Visitor: owns every logged visit. Fields include date_of_visit, isitor_name, isitor_company, eason_for_visit, is_us_citizen, 	ime_in, 	ime_out, and departed. Defaults for 	ime_in/date_of_visit (and 	ime_out when missing) rely on 	imezone.now; ordering is newest-first. Migrations show the earlier schema had TimeField fields and an id_confirm string before settling on the current design.
- Staged: temporary store for visitor info prior to check-in. Fields mirror the visitor record plus date_added (default 	imezone.now). Staged records are deleted when a check-in POST includes the matching staged_id.
- The app does not import models from other local apps; the only cross-app dependency is the shared conditional_login_required decorator.

## 6. Request / User Flow
- **Visitor log view (/accesslog/ or /accesslog/visitor_log/)**: isitor_log fetches all Visitor objects ordered by date/time, instantiates MonthYearForm, and renders the table/links in isitor_log.html. The form action for generate_report posts back to its own route.
- **Check-in form (/accesslog/check-in/)**: check_in_visitor displays the form with choices populated by VisitorHistoryField.populate_choices() and handles POSTs. When ction == 'stage', it creates a Staged record; otherwise it saves a Visitor, sets 	ime_in/date_of_visit, deletes the staged record if a staged_id was provided, and flashes success messages.
- **Check-out action (/accesslog/check-out/<visitor_id>/)**: POST sets 	ime_out, marks departed = True, saves, and redirects back to the log view.
- **Report export (/accesslog/generate-report/)**: POST from MonthYearForm filters visitors by the selected year/month, builds a ReportLab PDF (header, table headers, rows with truncated text, footer with generation timestamp), and streams it with a Content-Disposition attachment so the browser downloads isitor_log_<year>_<month>.pdf.
- **AJAX helpers**: get_visitor_info returns the most recent visitor matching the given name, while get_staged_info/<staged_id>/ returns the staged visitor data. The check-in template’s JavaScript calls these endpoints to populate fields and decide whether to treat the selection as staged or historical.

## 7. Templates and UI Surface Area
- Templates live under ccesslog/templates/accesslog/ and extend the shared ase_template.html.
- isitor_log.html includes the check-in link, inline MonthYearForm (rendered via Crispy Forms), and a table with badges showing citizenship and status, plus check-out buttons implemented as CSRF-protected POST forms. It is largely server-rendered with no extra scripts.
- check_in.html renders each form field manually for layout, adds a dropdown for previous visitors/staged entries, and uses inline JavaScript to fetch JSON payloads (isitor-info and staged-info); it also exposes action buttons for staging versus immediate check-in.
- There are no dedicated static assets (CSS or JS) within the app; styling comes from shared templates and inline scripts.

## 8. Admin / Staff Functionality
- The admin surface simply registers Visitor and Staged via dmin.site.register; there are no custom admin classes, so staff see a basic list/detail interface for each model.

## 9. Forms, Validation, and Input Handling
- VisitorHistoryField defers choice population until instantiation; it queries both Staged and Visitor, sorts by visitor name/company, and inserts labels such as Staged Visitors and Previous Visitors so the template can render separators.
- VisitorCheckInForm is a ModelForm for Visitor that also exposes the isitor_history field. Widgets are customized to apply consistent CSS classes, and labels are explicit. Validation relies on built-in checks; there are no additional clean methods.
- MonthYearForm has one ChoiceField populated by Visitor entries annotated with TruncMonth('date_of_visit') and ordered descending. If no visitor data exists, the dropdown stays at the placeholder, which prevents generate_report from executing and causes a redirect.

## 10. Business Logic and Services
- check_in_visitor differentiates between staging and final check-in, writes timestamps, cleans up staged records, and uses Django messages for user feedback. It also reinitializes VisitorCheckInForm with populated choices when re-displaying the form.
- check_out_visitor simply records the checkout time (	imezone.now()), marks departed, and saves.
- generate_report queries visitors for the requested month/year, builds a ReportLab PDF (headers, table layout, text truncation, footer timestamp), and streams the file back with Content-Disposition.
- get_visitor_info and get_staged_info return JSON payloads so the inline JavaScript can fill company, reason, and citizenship flags without loading the entire page.

## 11. Integrations and Cross-App Dependencies
- Each view is guarded by STATZWeb.decorators.conditional_login_required, so authentication/authorization rely on the shared decorator defined in the STATZWeb app.
- Report generation uses the third-party eportlab package; keep it listed in equirements.txt so generate_report succeeds.
- STATZWeb/urls.py wires this app at path('accesslog/', include('accesslog.urls')). No other app appears to import Visitor or Staged, so the app is otherwise isolated.

## 12. URL Surface / API Surface
| Route | Description |
| --- | --- |
| GET /accesslog/ and GET /accesslog/visitor_log/ | Render the visitor log table, show MonthYearForm, and display present/departed visitors. |
| GET/POST /accesslog/check-in/ | Display or process the check-in form, handle staging via ction = stage, and delete staged entries when a staged visitor is checked in. |
| POST /accesslog/check-out/<visitor_id>/ | Mark 	ime_out, set departed = True, and redirect to the visitor log. |
| POST /accesslog/generate-report/ | Accept month_year, filter visitors, build a ReportLab PDF, and stream it as isitor_log_<year>_<month>.pdf. |
| GET /accesslog/visitor-info/?name=<visitor_name> | Return JSON with the most recent visitor for that name. |
| GET /accesslog/staged-info/<staged_id>/ | Return JSON for the staged visitor so the form can auto-fill company and reason. |

## 13. Permissions / Security Considerations
- All views use conditional_login_required, so only authenticated users defined by that decorator can reach any visitor endpoints.
- There are no object-level permissions; any logged-in user can stage, check in, check out, or download PDFs. Introduce additional checks upstream if only specific staff should use these endpoints.
- generate_report trusts the month_year value validated by MonthYearForm; malformed or empty values cause orm.is_valid() to fail and redirect without explicit feedback.
- check_out_visitor uses Visitor.objects.get(id = visitor_id) without 	ry/except, so invalid IDs posted manually would raise Visitor.DoesNotExist and return a 500 response unless the view is refactored.
- PDF exports contain sensitive visitor data, so keep an eye on how and where those files are shared.

## 14. Background Processing / Scheduled Work
- There are no Celery tasks, signal handlers, or scheduled jobs in this app. The only longer-running task is the synchronous PDF build triggered by generate_report.

## 15. Testing Coverage
- 	ests.py contains only the default comment placeholder. There are currently no automated tests covering models, forms, or views.

## 16. Migrations / Schema Notes
- Five migrations ( 001_initial through  005_alter_visitor_time_in_alter_visitor_time_out) live under ccesslog/migrations/. They document how the schema evolved from the initial Visitor table to the current datetime fields plus the Staged model with date_added and is_us_citizen.
- No migrations exist beyond  005. Changing fields referenced in the report PDF or form choice builders requires a new migration and a ripple-through update.

## 17. Known Gaps / Ambiguities
- No automated tests exist, so any change to the flows is unguarded by regression coverage.
- check_in.html includes console.log statements and depends on exact dropdown formatting (value is either a staged id or Name - Company), so altering VisitorHistoryField requires coordinated template and JavaScript changes.
- The conditional_login_required decorator is defined elsewhere, so its exact behavior (redirect target, group limits) is unknown inside this app.
- generate_report redirects without user feedback if the dropdown stays at the placeholder, so users get no error message when they submit without selecting a month.

## 18. Safe Modification Guidance for Future Developers / AI Agents
- When renaming or adding fields on Visitor or Staged, update orms.py, iews.py (PDF data, JSON helpers, staging flow), templates (field IDs/labels), and provide a migration. The PDF builder expects specific columns and headings.
- Editing VisitorHistoryField labels or values requires updating the JavaScript in check_in.html that treats numeric values as staged visitors and string values as history entries.
- Keep the eportlab dependency in sync with equirements.txt before touching generate_report.
- Because staged records are deleted during check-in, confirm any change still cleans up the Staged row unless the new flow intentionally preserves it.
- Wrap Visitor.objects.get in get_object_or_404 or similar before expanding check_out_visitor so malformed IDs no longer raise unintended 500 errors.

## 19. Quick Reference
- **Primary models**: Visitor, Staged.
- **Main URLs**: isitor_log, check_in, check_out, generate_report, isitor_info, staged_info under the ccesslog namespace.
- **Key templates**: 	emplates/accesslog/visitor_log.html, 	emplates/accesslog/check_in.html.
- **Key dependencies**: STATZWeb.decorators.conditional_login_required, eportlab, Django messages.
- **Risky files**: ccesslog/views.py (PDF generation, staging checks, check-in/out logic) and ccesslog/forms.py (VisitorHistoryField and MonthYearForm).
