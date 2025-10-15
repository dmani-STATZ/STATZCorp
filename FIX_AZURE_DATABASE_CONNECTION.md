# 🚀 Fix Azure Database Connection - Action Plan

## 🎯 Current Issue
```
Database Connection failed: ('HYT00', '[HYT00] [Microsoft][ODBC Driver 17 for SQL Server] Login timeout expired (0) (SQLDriverConnect)')
```

## 📋 Step-by-Step Fix Process

### Step 1: Verify Azure SQL Server Configuration ⚙️

1. **Check Server Name Format**
   - Go to Azure Portal → SQL Servers → Your Server
   - Server name should be: `yourserver.database.windows.net`
   - NOT just: `yourserver`

2. **Verify Database Name**
   - Check the exact database name (case-sensitive)
   - No special characters or spaces

3. **Check Username Format**
   - Should be: `username@servername`
   - Example: `admin@yourserver`

### Step 2: Configure Firewall Rules 🔥

1. **Azure Portal → SQL Servers → Your Server → Networking**
2. **Enable "Allow Azure services and resources to access this server"**
3. **Add Firewall Rule:**
   - Rule Name: `AzureServices`
   - Start IP: `0.0.0.0`
   - End IP: `0.0.0.0`
   - Description: "Allow Azure Services"

### Step 3: Set Environment Variables 🔧

**In Azure App Service Configuration:**

```bash
DB_NAME=your_exact_database_name
DB_USER=your_username@yourserver
DB_PASSWORD=your_secure_password
DB_HOST=yourserver.database.windows.net
DJANGO_SECRET_KEY=your-super-secure-secret-key-here
DJANGO_DEBUG=False
REQUIRE_LOGIN=True
```

**How to set:**
1. Azure Portal → App Service → Configuration
2. Add each variable with its value
3. Click "Save" and restart the app

### Step 4: Test the Connection 🧪

1. **Use the System Test Page:**
   - Visit: `https://your-app.azurewebsites.us/system-test/`
   - Check the "Database Connection" test

2. **Run the Database Test Script:**
   ```bash
   # SSH into your App Service
   az webapp ssh --name your-app-name --resource-group your-rg
   
   # Run the test
   python test_azure_db_connection.py
   ```

### Step 5: Verify Fix ✅

**Success indicators:**
- ✅ System test shows "Database Connection: PASS"
- ✅ Database test script shows "Connection successful!"
- ✅ No timeout errors in logs
- ✅ Application loads without database errors

## 🔧 Quick Commands

### Set Environment Variables (Azure CLI)
```bash
az webapp config appsettings set --name your-app-name --resource-group your-rg --settings DB_NAME="your_database_name"
az webapp config appsettings set --name your-app-name --resource-group your-rg --settings DB_USER="your_username@yourserver"
az webapp config appsettings set --name your-app-name --resource-group your-rg --settings DB_PASSWORD="your_password"
az webapp config appsettings set --name your-app-name --resource-group your-rg --settings DB_HOST="yourserver.database.windows.net"
az webapp config appsettings set --name your-app-name --resource-group your-rg --settings DJANGO_SECRET_KEY="your-secret-key"
az webapp config appsettings set --name your-app-name --resource-group your-rg --settings DJANGO_DEBUG="False"
```

### Restart App Service
```bash
az webapp restart --name your-app-name --resource-group your-rg
```

### Check Current Settings
```bash
az webapp config appsettings list --name your-app-name --resource-group your-rg
```

## 🚨 Common Issues & Solutions

### Issue: "Login timeout expired"
**Solutions:**
- ✅ Enable "Allow Azure services" in firewall
- ✅ Check server name includes `.database.windows.net`
- ✅ Verify username format includes `@servername`

### Issue: "Login failed for user"
**Solutions:**
- ✅ Check username and password are correct
- ✅ Verify user exists in the database
- ✅ Check user has proper permissions

### Issue: "Server not found"
**Solutions:**
- ✅ Verify server name is correct
- ✅ Check if server is running
- ✅ Ensure DNS resolution works

## 📊 Expected Results

After fixing, your system test should show:

```
✅ Database Connection: PASS
   - Database engine: mssql
   - Database name: your_database_name
   - Database host: yourserver.database.windows.net
   - Version: Microsoft SQL Server 2019...
   - Table count: [number of tables]
```

## 🆘 If Still Having Issues

1. **Check Azure SQL Server Logs**
2. **Verify App Service can reach SQL Server**
3. **Test with Azure Portal Query Editor**
4. **Contact Azure Support if needed**

## 📞 Next Steps

1. **Follow the steps above** in order
2. **Test each step** before moving to the next
3. **Use the system test page** to verify fixes
4. **Check logs** for any remaining errors
5. **Deploy and test** your application

---

**Remember:** The system test page is your best friend for diagnosing these issues! 🎯
