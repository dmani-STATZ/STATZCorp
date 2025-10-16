# STATZWeb Development Setup

This guide helps you set up and run STATZWeb in development mode.

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Database Migrations
```bash
python manage.py migrate
```

### 3. Create a Superuser (Optional)
```bash
python manage.py createsuperuser
```

### 4. Start Development Server

**With Login Required (Default):**
```bash
python manage.py runserver
```

**Without Login (Bypass Authentication):**
```bash
python dev_commands.py no-login
```

## Development Commands

Use the `dev_commands.py` script for easy development workflow:

```bash
# Start server with login
python dev_commands.py start

# Start server without login (for testing)
python dev_commands.py no-login

# Run migrations
python dev_commands.py migrate

# Create superuser
python dev_commands.py superuser

# Check Django configuration
python dev_commands.py check

# Open Django shell
python dev_commands.py shell
```

## Environment Configuration

### Consolidated Settings
- **Single Settings File**: `STATZWeb.settings` handles both development and production
- **Auto-Detection**: Automatically detects environment based on `WEBSITE_SITE_NAME` variable
- **Development**: Uses `.env` file, SQLite database, debug enabled
- **Production**: Uses Azure environment variables, SQL Server database, debug disabled

### Environment Variables
Create a `.env` file from `env.dev.example`:
```bash
cp env.dev.example .env
```

Key settings:
- `REQUIRE_LOGIN=True/False` - Enable/disable login requirement
- `DJANGO_DEBUG=True/False` - Enable/disable debug mode
- `DB_HOST`, `DB_NAME`, etc. - Optional SQL Server for development

## Development vs Production

### Development Mode (Default)
- **Environment**: Detected by absence of `WEBSITE_SITE_NAME`
- **Database**: SQLite (can be overridden with DB_* environment variables)
- **Debug**: Enabled with verbose logging
- **Login**: Optional (set `REQUIRE_LOGIN=False` in .env)
- **Static Files**: Standard Django static files
- **Security**: Relaxed for development

### Production Mode
- **Environment**: Detected by presence of `WEBSITE_SITE_NAME` (Azure App Service)
- **Database**: Azure SQL Server (requires DB_* environment variables)
- **Debug**: Disabled
- **Login**: Required (set `REQUIRE_LOGIN=True`)
- **Static Files**: WhiteNoise for Azure
- **Security**: Full production security settings

## Troubleshooting

### Server Won't Start
1. Check if all dependencies are installed: `pip install -r requirements.txt`
2. Run Django check: `python manage.py check`
3. Check for missing migrations: `python manage.py migrate`

### Login Page Not Showing
- By default, login is required in development
- To bypass login: `python dev_commands.py no-login`
- To enable login: `python dev_commands.py with-login`

### Database Issues
- Development uses SQLite by default
- If you need SQL Server for development, set DB_* environment variables in .env file

## File Structure

```
STATZWeb/
├── settings.py          # Consolidated settings (dev + production)
├── manage.py            # Django management (uses consolidated settings)
├── dev_commands.py      # Development helper script
├── requirements.txt     # All dependencies
├── env.dev.example     # Environment variables template
└── .env                # Your local environment variables (not in git)
```

## Next Steps

1. **Start developing**: `python dev_commands.py start`
2. **Access the app**: http://127.0.0.1:8000
3. **Create superuser**: `python dev_commands.py superuser`
4. **Make changes**: The server auto-reloads when you save files

## Deployment

When ready to deploy:
1. Set `DJANGO_SETTINGS_MODULE=STATZWeb.settings`
2. Configure production environment variables
3. Use production database settings
4. Deploy using your preferred method (Azure, etc.)
