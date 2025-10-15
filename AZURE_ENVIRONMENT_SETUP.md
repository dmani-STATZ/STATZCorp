# Azure Environment Variables Setup Guide

## 🔧 Required Environment Variables for Azure App Service

### Database Configuration
```bash
# SQL Server Database
DB_NAME=your_database_name
DB_USER=your_username@yourserver
DB_PASSWORD=your_secure_password
DB_HOST=yourserver.database.windows.net
```

### Django Configuration
```bash
# Django Secret Key (generate a new one for production)
DJANGO_SECRET_KEY=your-super-secret-key-here

# Debug Mode (set to False for production)
DJANGO_DEBUG=False

# Login Requirement (set to True for production)
REQUIRE_LOGIN=True
```

### Azure AD Authentication (Optional)
```bash
# Microsoft Authentication
MICROSOFT_AUTH_CLIENT_ID=your-client-id
MICROSOFT_AUTH_CLIENT_SECRET=your-client-secret
MICROSOFT_AUTH_TENANT_ID=your-tenant-id
MICROSOFT_AUTH_REDIRECT_URI=https://your-app.azurewebsites.us/microsoft/auth-callback/
```

### Email Configuration (Optional)
```bash
# Report Creator Email
REPORT_CREATOR_EMAIL=admin@statzcorp.com
```

## 🚀 How to Set Environment Variables in Azure

### Method 1: Azure Portal
1. Go to your App Service in Azure Portal
2. Navigate to **Settings** → **Configuration**
3. Click **+ New application setting**
4. Add each variable with its value
5. Click **Save** to apply changes

### Method 2: Azure CLI
```bash
# Set database variables
az webapp config appsettings set --name your-app-name --resource-group your-rg --settings DB_NAME="your_database_name"
az webapp config appsettings set --name your-app-name --resource-group your-rg --settings DB_USER="your_username@yourserver"
az webapp config appsettings set --name your-app-name --resource-group your-rg --settings DB_PASSWORD="your_secure_password"
az webapp config appsettings set --name your-app-name --resource-group your-rg --settings DB_HOST="yourserver.database.windows.net"

# Set Django variables
az webapp config appsettings set --name your-app-name --resource-group your-rg --settings DJANGO_SECRET_KEY="your-super-secret-key"
az webapp config appsettings set --name your-app-name --resource-group your-rg --settings DJANGO_DEBUG="False"
az webapp config appsettings set --name your-app-name --resource-group your-rg --settings REQUIRE_LOGIN="True"
```

### Method 3: Azure PowerShell
```powershell
# Set multiple variables at once
$appSettings = @{
    "DB_NAME" = "your_database_name"
    "DB_USER" = "your_username@yourserver"
    "DB_PASSWORD" = "your_secure_password"
    "DB_HOST" = "yourserver.database.windows.net"
    "DJANGO_SECRET_KEY" = "your-super-secret-key"
    "DJANGO_DEBUG" = "False"
    "REQUIRE_LOGIN" = "True"
}

Set-AzWebApp -ResourceGroupName "your-rg" -Name "your-app-name" -AppSettings $appSettings
```

## 🔐 Security Best Practices

### 1. Generate a Strong Secret Key
```python
# Run this in Python to generate a secure secret key
import secrets
print(secrets.token_urlsafe(50))
```

### 2. Use Azure Key Vault (Recommended)
```bash
# Store sensitive values in Azure Key Vault
az keyvault secret set --vault-name your-vault --name "db-password" --value "your-password"
az keyvault secret set --vault-name your-vault --name "django-secret" --value "your-secret-key"

# Reference in App Service
az webapp config appsettings set --name your-app-name --resource-group your-rg --settings DB_PASSWORD="@Microsoft.KeyVault(SecretUri=https://your-vault.vault.azure.net/secrets/db-password/)"
```

### 3. Database User Format
For Azure SQL Server, use the format: `username@servername`
- Username: Your database username
- Servername: Your SQL Server name (without .database.windows.net)

## 🧪 Testing Your Configuration

### 1. Use the System Test Page
Visit: `https://your-app.azurewebsites.us/system-test/`

### 2. Run the Database Test Script
```bash
# SSH into your App Service
az webapp ssh --name your-app-name --resource-group your-rg

# Run the test script
python test_azure_db_connection.py
```

### 3. Check Environment Variables
```bash
# In App Service SSH
printenv | grep -E "(DB_|DJANGO_|MICROSOFT_)"
```

## 🚨 Common Issues and Solutions

### Issue 1: Database Connection Timeout
**Solution:**
- Check firewall rules in Azure SQL Server
- Verify server name format includes `.database.windows.net`
- Ensure username includes `@servername`

### Issue 2: Environment Variables Not Loading
**Solution:**
- Restart the App Service after setting variables
- Check variable names are exactly correct (case-sensitive)
- Verify no extra spaces in values

### Issue 3: Secret Key Issues
**Solution:**
- Generate a new secret key using the Python script above
- Ensure it's at least 50 characters long
- Don't use the default development key

## 📋 Verification Checklist

- [ ] All required environment variables are set
- [ ] Database connection string is correct
- [ ] Firewall rules allow Azure services
- [ ] Secret key is generated and secure
- [ ] Debug mode is set to False
- [ ] Login requirement is set to True
- [ ] System test page shows green status
- [ ] Database test script passes

## 🔗 Useful Commands

### Check Current Settings
```bash
az webapp config appsettings list --name your-app-name --resource-group your-rg
```

### Restart App Service
```bash
az webapp restart --name your-app-name --resource-group your-rg
```

### View Logs
```bash
az webapp log tail --name your-app-name --resource-group your-rg
```

## 📞 Next Steps

1. **Set all environment variables** using one of the methods above
2. **Restart your App Service** to apply changes
3. **Run the system test page** to verify configuration
4. **Check the database test script** for detailed diagnostics
5. **Monitor logs** for any remaining issues
