# CONTEXT_mailer.md — `mailer` App

## 1. Domain Purpose
The `mailer` app is responsible for orchestrating highly personalized, large-scale outbound email campaigns to suppliers or contacts. It provides the ability to import recipients (either via CSV or a dynamic SQL audience builder), generate AI-driven personalized icebreakers or content via Anthropic's Claude, and dispatch those emails using Microsoft Graph API. It also handles sequenced follow-up emails based on predefined intervals.

## 2. Core Entities
- **Campaign**: The top-level container for a mailer effort. Holds the subject/body templates, the sender email address, the status of the campaign (`DRAFT`, `SCHEDULED`, `SENDING`, `COMPLETED`, `FAILED`), and AI generation instructions/status.
- **CampaignRecipient**: An individual target within a campaign. Stores their email, name, company, and a `custom_data` JSON field holding any extra dynamic variables (e.g., historical win metrics) parsed from the audience builder or CSV. Also tracks the recipient's current progress in the follow-up sequence.
- **CampaignFollowUp**: Defines a scheduled follow-up step for a campaign. Specifies a `delay_days` (how long to wait after the previous email), and optional custom `subject_template` and `body_template`.

## 3. Key Workflows
### Audience Building & Import
Recipients are added to campaigns in two primary ways:
1. **CSV Import**: Users upload a CSV file with `email`, `first_name`, `last_name`, and `company_name`. Any additional columns are packed into the `custom_data` JSON object automatically.
2. **Dynamic Audience Builder**: Users can execute pre-defined SQL queries (stored in `mailer/services/audience_builder.py`) to harvest contacts from the core STATZ database (e.g., from `suppliers` or `contracts`). The resulting data is merged into `custom_data`.

### AI Personalization
Users can write an `ai_instruction` (e.g., "Write a personalized 2-sentence icebreaker...") on the campaign. When triggered, the background task `process_ai_snippets` batches the recipients and sends their `custom_data` stats to Claude. Claude returns unique messages for each recipient, which are saved as `ai_custom_message` inside the JSON `custom_data` field. The template can then simply inject `{ai_custom_message}`.

### Dispatching
When a user sets a campaign to `SCHEDULED`, the `dispatch_campaigns` background task picks it up. It formats the subject and body using Python's `.format(**context)` with the recipient's `custom_data` and sends the email via `send_mail_via_graph`. Plain-text templates are auto-linked and converted to HTML before dispatch.

### Follow-Ups
The `dispatch_followups` background task periodically checks for completed campaigns that have follow-ups enabled. It identifies recipients who successfully received the initial email and whose `delay_days` have elapsed since their `last_contact_date`. It then sends the next `CampaignFollowUp` step in the sequence.

## 4. Background Tasks
There is no Celery in this app. All background processing is orchestrated by the `core` app's WebJob heartbeat (`run_background_tasks.py`).
- **`dispatch_campaigns`**: Sends initial emails for `SCHEDULED` campaigns.
- **`process_ai_snippets`**: Generates AI messages for `PROCESSING` campaigns in chunks of 30.
- **`dispatch_followups`**: Processes sequenced follow-ups for `COMPLETED` campaigns.
