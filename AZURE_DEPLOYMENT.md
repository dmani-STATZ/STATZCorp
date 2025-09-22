# Azure App Service Deployment Guide

## Prerequisites
- Azure App Service with Python 3.9+ runtime
- SQL Server database (Azure SQL Database recommended)
- Azure AD app registration for authentication

## Environment Variables
Configure these in Azure App Service Application Settings:

### Required Settings
```
DJANGO_SECRET_KEY=your-secret-key-here
DJANGO_DEBUG=False
DB_NAME=your-database-name
DB_USER=your-database-user
DB_PASSWORD=your-database-password
DB_HOST=your-database-server.database.windows.net
```

### Azure AD Authentication
```
MICROSOFT_AUTH_CLIENT_ID=your-azure-ad-app-id
MICROSOFT_AUTH_CLIENT_SECRET=your-azure-ad-app-secret
MICROSOFT_AUTH_TENANT_ID=your-azure-ad-tenant-id
MICROSOFT_REDIRECT_URI=https://your-app-name.azurewebsites.us/microsoft/auth-callback/
```

### Optional Settings
```
REPORT_CREATOR_EMAIL=admin@yourcompany.com
```

## Deployment Steps

1. **Deploy to Azure App Service**
   - Use Git deployment or Azure DevOps
   - Ensure Python 3.9+ runtime is selected

2. **Configure Database**
   - Set up Azure SQL Database
   - Configure connection string in App Settings
   - Run migrations: `python manage.py migrate`

3. **Configure Static Files**
   - Static files are served by WhiteNoise
   - No additional configuration needed

4. **Configure Authentication**
   - Set up Azure AD app registration
   - Configure redirect URIs
   - Set environment variables

5. **Test Deployment**
   - Visit your app URL
   - Test authentication flow
   - Verify all features work

## Troubleshooting

### Common Issues
- **Database Connection**: Verify connection string and firewall rules
- **Static Files**: Check WhiteNoise configuration
- **Authentication**: Verify Azure AD app configuration
- **Logs**: Check Azure App Service logs for errors

### Log Locations
- Application logs: Azure Portal > App Service > Log stream
- Django logs: `/home/LogFiles/django.log`
