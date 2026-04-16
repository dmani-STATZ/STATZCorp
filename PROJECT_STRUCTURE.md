# STATZCorp Project Structure

Django project layout aligned with standard conventions.

## Root (project root)

| Item | Purpose |
|------|--------|
| `manage.py` | Django CLI entry point. |
| `STATZWeb/` | **Project package**: settings, root URLs, WSGI, middleware, context processors, version utils. |
| `requirements.txt` | Production/primary dependencies. |
| `requirements-dev.txt` | Optional dev tooling. |
| `.env` | Local env vars (not in repo). |
| `version_info.json` | Build/version info (used by STATZWeb at runtime). |
| `db.sqlite3` | Default dev database (git-ignored in most setups). |
| `web.config`, `Procfile`, `startup.sh`, `.deployment` | Deployment config (Azure, Heroku, etc.). |

## Django apps (at root)

Each app is a package with `models`, `views`, `urls`, `admin`, etc.:

- `users` — Auth, companies, preferences
- `inventory` — Inventory
- `contracts` — Contracts, CLINs, suppliers, NSNs, DD1155
- `accesslog` — Access logging
- `processing` — Processing
- `training` — Training
- `reports` — Reports
- `suppliers` — Suppliers
- `products` — Products
- `tools` — Tools
- `transactions` — Transactions
- `td_now` — TD Now (tower defense)

## Shared assets

| Path | Purpose |
|------|--------|
| `templates/` | Project-level templates (DIRS in settings). |
| `static/` | Project-level static files (STATICFILES_DIRS). |
| `staticfiles/` | Collected static output (STATIC_ROOT). |
| `media/` | Uploaded files (MEDIA_ROOT in dev). |
| `logs/` | Log files (when file logging is used). |

## Other

| Path | Purpose |
|------|--------|
| `_extra/` | Scripts and files not needed for a normal run (see `_extra/README.md`). |
| `scripts/` | Utility scripts. |
| `SQL/` | SQL scripts. |
| `docs/` | Documentation. |
| `.cursor/`, `.github/`, `.vscode/` | Tooling and CI config. |

## Running

From project root:

```bash
python manage.py runserver
python manage.py migrate
```
