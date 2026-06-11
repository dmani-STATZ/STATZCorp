# AGENTS.md — `mailer` App
> Read `mailer/CONTEXT.md` first.

## 1. Purpose of This File
Safe-edit guidance for the `mailer` backend (campaign management, CSV import, AI generation, Graph dispatch, and follow-ups).

## 2. App Scope
**Owns:**
- `Campaign`, `CampaignRecipient`, `CampaignFollowUp`
- Email AI generation logic (`tasks/generate_ai.py`)
- Background dispatchers (`tasks/dispatch_campaigns.py`, `tasks/dispatch_followups.py`)
- Dynamic audience queries (`services/audience_builder.py`)
- Internal UI templates (`mailer/*`)

**Does not own:**
- Global background task orchestrator (`core.management.commands.run_background_tasks`)
- `Anthropic` API billing or wrappers (`core/anthropic_client.py`)
- `services/graph_mail.py` is widely imported by other apps, but lives here.

## 3. Files That Commonly Need to Change Together
| Change | Files that must move together |
|---|---|
| Adding a new dynamic audience query | `mailer/services/audience_builder.py` (`AUDIENCE_QUERIES`) + `campaign_audience.html` |
| Changing Campaign status choices | `models.py` (`STATUS_CHOICES`) + `dispatch_campaigns.py` + `views.py` |
| Adding Campaign properties | `models.py` + `forms.py` (`CampaignForm`) + `views.py` + `campaign_detail.html` / `campaign_form.html` |
| Changing Email formatting logic | `dispatch_campaigns.py` + `dispatch_followups.py` + `recipient_preview.html` |

## 4. Cross-App Dependency Warnings
- Depends on `core.anthropic_client.call_anthropic` for AI generation.
- `services/graph_mail.py` is widely imported by other apps (e.g., `reports`, `sales`). Do not change its signature (`send_mail_via_graph`) or default `contentType` behavior without exhaustive codebase search and regression testing. (An `is_html=False` parameter was added to support mailer HTML auto-linking while preserving backward compatibility).
- Background tasks (`dispatch_campaigns`, `process_ai_snippets`, `dispatch_followups`) must be registered in `core/management/commands/run_background_tasks.py` and require a corresponding row in `core.ScheduledTask`.

## 5. Security / Permissions Rules
- Keep `@login_required` on all views.
- `send_mail_via_graph` utilizes Microsoft Graph App-Only credentials. Do not expose client secrets or tenant IDs in views or templates.
- Ensure any SQL executed via `audience_builder.py` is strictly read-only and does not accept unparameterized user input to prevent SQL injection.

## 6. Model and Schema Change Rules
- `CampaignRecipient.custom_data` is a JSONField. When modifying import logic, ensure keys do not collide with reserved context variables (`email`, `first_name`, `last_name`, `company_name`).
- When parsing custom JSON, do not store plain JSON strings in `custom_data` via raw SQL or manual edits—always use standard Django `JSONField` dictionary packing, otherwise background tasks will raise `TypeError` when unpacking `**recipient.custom_data`.

## 7. Background Tasks / Automation
No Celery/tasks in this app. Background processing relies on the central `core` scheduled WebJob.
- **`dispatch_campaigns`**: Runs in the background to avoid locking the UI on large sends.
- **`process_ai_snippets`**: Batches Anthropic calls in chunks of 30 to avoid rate limits and connection timeouts. Always use `call_anthropic` for centralized tracking.
- **`dispatch_followups`**: Validates the `delay_days` interval against the recipient's `last_contact_date` (or `sent_at`) before sending the next sequence step.

## 8. Known Footguns
- The `is_html` parameter in `send_mail_via_graph` is required to be `True` if `urlize` and `linebreaks` are applied to the body. Missing this causes emails to be sent as raw HTML text.
- Template rendering utilizes `.format(**context)`. Since curly braces `{}` are used for context injection, any stray curly braces in the user's template will raise `KeyError` if not escaped or explicitly handled. Currently, KeyError drops the unmatched token, but complex templates could break.
- Modifying `dispatch_followups.py` error handling logic: failing to mark `recipient.follow_up_active = False` on persistent format errors can result in an infinite loop of failed send attempts.
