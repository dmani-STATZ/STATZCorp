# STATZ Mailer Walkthrough

The STATZ Email Blast System has been fully built as a new built-in app called `mailer`. It utilizes the existing Microsoft Graph integration (used for DIBBS RFQs) to send personalized emails securely from within the STATZ GCC High environment.

## What's New

### 1. New Mailer App
We created a new app dedicated entirely to email campaigns, keeping the codebase clean. This app includes its own database tables:
* `Campaign`: Represents the email blast (name, subject, body, sender, status).
* `CampaignRecipient`: Represents a person on the list (email, name, company, delivery status).

### 2. Graph Mail Centralization
The `sales/services/graph_mail.py` file, which handles sending email through Microsoft's GCC High Graph API, has been relocated to `mailer/services/graph_mail.py`. This solidifies `mailer` as the true central home for outbound Graph emails. 
* *All existing background tasks and systems (like the automated DIBBS RFQ emailer) have been updated to use the new path seamlessly.*

### 3. Contact Importing (Version 1)
When building your list of recipients, you have two options:
* **CSV Import**: Upload a CSV file with columns like `email`, `first_name`, `last_name`, and `company_name`. Any extra columns you include in the CSV are saved under the hood, setting us up nicely for future LLM-based personalization.
* **Quick Text Input**: Simply paste a semicolon-separated list of emails into the text box (e.g. `dion@statzcorp.com; mark@statzcorp.com`).

### 4. Background Dispatching
When you click **Send Campaign**, it does not freeze the website trying to send hundreds of emails at once. Instead, it flips the campaign to `SCHEDULED`. 

A new background task (`mailer.tasks.dispatch_campaigns.py`) has been wired into your existing Azure WebJobs runner (`core.management.commands.run_background_tasks.py`). It will automatically wake up, grab the scheduled campaigns, build the personalized emails (replacing `{first_name}`, etc.), and blast them out via Microsoft Graph.

## How to use it

1. Look in the left sidebar under the **Tools** section. You will see a new link for **Email Campaigns**.
2. Click **Create Campaign**. Here, you can specify exactly who the email should look like it's coming from (e.g. `mark@statzcorp.com`).
3. You can use curly braces in your subject or body for personalization (e.g. `Hello {first_name}, it's been a while since we worked with {company_name}!`).
4. Import your contacts via CSV or text box.
5. Review the recipients list and click **Send Campaign**.

## Next Steps for Future Iterations

* **LLM Personalization**: Tapping into the `custom_data` JSON field we built for recipients to use Anthropic/Gemini to write custom sentences based on past order history.
* **Follow-up Drip Campaigns**: Adding logic for "Email 2" if no response after 3 days.
