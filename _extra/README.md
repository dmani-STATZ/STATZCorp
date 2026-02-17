# Extra / Non-Essential Files

This folder contains files that are **not required for a clean run** of the application and are not imported or called from the project root.

## Contents

| File | Description |
|------|-------------|
| `dev_commands.py` | Development workflow helper (start server, migrate, etc.). Run with `python _extra/dev_commands.py <command>` if needed. |
| `setup_dev.py` | One-time development environment setup script. |
| `env.dev.example` | Example environment file; copy to `.env` in project root when setting up. |
| `htaccess.conf` | Apache config snippet; not used by Django runserver or typical Azure deployment. |
| `temp_contract_log_views.py` | Temporary/scratch code. |
| `temp_req.txt` | Temporary requirements or notes. |
| `test_azure_db_connection.py` | Standalone script to test Azure DB connection. |
| `test_open_system_test.py` | Standalone test script. |
| `test_system_tests.py` | Standalone test script. |
| `test_version_display.py` | Standalone test script. |
| `themeing.md` | Theme documentation/notes. |
| `tmp.js` | Temporary JavaScript. |
| `tmp_read_xlsx.py` | Temporary/scratch script. |
| `VISUAL_TEST.html` | Visual test page. |

## Running the app

From the **project root** (parent of `_extra`):

- `python manage.py runserver` — start dev server
- `python manage.py migrate` — run migrations
- Use `requirements.txt` and optionally `requirements-dev.txt` in the root for dependencies.
