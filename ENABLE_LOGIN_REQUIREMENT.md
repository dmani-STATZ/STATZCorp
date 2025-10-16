# Enable Login Requirement - Quick Guide

## 🎯 Current Status
- ✅ Database connection fixed
- ✅ System test page removed from landing page
- 🔄 Need to enable login requirement

## 🚀 Quick Fix

### Option 1: Azure Portal (Recommended)
1. Go to **Azure Portal** → **App Services** → **Your App Service**
2. Navigate to **Settings** → **Configuration**
3. Find the `REQUIRE_LOGIN` setting
4. Change its value from `False` to `True`
5. Click **Save**
6. **Restart** your App Service

### Option 2: Azure CLI
```bash
az webapp config appsettings set --name your-app-name --resource-group your-rg --settings REQUIRE_LOGIN="True"
az webapp restart --name your-app-name --resource-group your-rg
```

### Option 3: Azure PowerShell
```powershell
Set-AzWebApp -ResourceGroupName "your-rg" -Name "your-app-name" -AppSettings @{"REQUIRE_LOGIN"="True"}
Restart-AzWebApp -ResourceGroupName "your-rg" -Name "your-app-name"
```

## ✅ Verification

After enabling login requirement:

1. **Visit your landing page** - should show only "Accept & Continue" button
2. **Click "Accept & Continue"** - should redirect to login page
3. **Try accessing any protected page directly** - should redirect to login
4. **System test page** - should still be accessible at `/system-test/` (for troubleshooting)

## 🔧 Current Environment Variables

Make sure these are set in your Azure App Service:

```bash
# Database (should be working now)
DB_NAME=your_database_name
DB_USER=your_username@yourserver
DB_PASSWORD=your_password
DB_HOST=yourserver.database.windows.net

# Django Security
DJANGO_SECRET_KEY=your-secure-secret-key
DJANGO_DEBUG=False

# Login Requirement (THIS IS WHAT WE'RE CHANGING)
REQUIRE_LOGIN=True

# Optional: Azure AD Authentication
MICROSOFT_AUTH_CLIENT_ID=your-client-id
MICROSOFT_AUTH_CLIENT_SECRET=your-client-secret
MICROSOFT_AUTH_TENANT_ID=your-tenant-id
```

## 🎉 Expected Result

After enabling login requirement:
- ✅ Landing page shows only "Accept & Continue" button
- ✅ Clicking button redirects to login page
- ✅ All protected pages require authentication
- ✅ System test page remains accessible for troubleshooting
- ✅ Version information still displays on landing page

## 🆘 If Issues Occur

1. **Check environment variables** are set correctly
2. **Restart the App Service** after making changes
3. **Check logs** for any errors
4. **Use system test page** to verify database connection still works

---

**The system test page will remain accessible at `/system-test/` for future troubleshooting needs!** 🛠️
