# Azure SQL Server Connection Troubleshooting Guide

## 🚨 Current Error
```
Database Connection failed: ('HYT00', '[HYT00] [Microsoft][ODBC Driver 17 for SQL Server] Login timeout expired (0) (SQLDriverConnect)')
```

## 🔍 Root Cause Analysis
The "Login timeout expired" error typically indicates one of these issues:

1. **Firewall Rules** - Azure SQL Server firewall blocking your connection
2. **Connection String Issues** - Incorrect server name, credentials, or parameters
3. **Network Connectivity** - Azure App Service can't reach SQL Server
4. **Server Configuration** - SQL Server not properly configured

## 🛠️ Step-by-Step Fix

### Step 1: Verify Azure SQL Server Configuration

1. **Check Server Name Format**
   ```
   Correct: yourserver.database.windows.net
   Incorrect: yourserver
   ```

2. **Verify Port**
   - Default port: 1433
   - Ensure it's not blocked by firewall

3. **Check Database Name**
   - Must match exactly (case-sensitive)
   - No special characters or spaces

### Step 2: Configure Firewall Rules

1. **Azure Portal → SQL Servers → Your Server → Networking**
2. **Add Firewall Rule:**
   - Rule Name: `AzureServices`
   - Start IP: `0.0.0.0`
   - End IP: `0.0.0.0`
   - Description: "Allow Azure Services"

3. **Add Your App Service IP:**
   - Find your App Service outbound IPs
   - Add each IP as a firewall rule

### Step 3: Update Connection String

Your current connection string should look like this:

```python
DATABASES = {
    'default': {
        'ENGINE': 'mssql',
        'NAME': 'your_database_name',
        'USER': 'your_username@yourserver',
        'PASSWORD': 'your_password',
        'HOST': 'yourserver.database.windows.net',
        'OPTIONS': {
            'driver': 'ODBC Driver 17 for SQL Server',
            'timeout': 30,  # Increase timeout
            'autocommit': True,
        },
    },
}
```

### Step 4: Environment Variables Check

Ensure these are set in your Azure App Service:

```bash
DB_NAME=your_database_name
DB_USER=your_username@yourserver
DB_PASSWORD=your_password
DB_HOST=yourserver.database.windows.net
```

### Step 5: Test Connection

1. **Use Azure Portal Query Editor**
   - Go to your SQL Server in Azure Portal
   - Use "Query editor" to test basic connectivity

2. **Test from App Service**
   - Use the system test page we created
   - Check the detailed error information

## 🔧 Advanced Troubleshooting

### Option 1: Enable Azure Services Access
1. Azure Portal → SQL Server → Networking
2. Enable "Allow Azure services and resources to access this server"
3. This allows all Azure services to connect

### Option 2: Use Private Endpoint
1. Create a private endpoint for your SQL Server
2. This provides more secure connectivity
3. Requires VNet configuration

### Option 3: Check ODBC Driver
Ensure the correct ODBC driver is installed:
```bash
# Check available drivers
odbcinst -q -d
```

## 📋 Verification Checklist

- [ ] Server name includes `.database.windows.net`
- [ ] Username includes `@servername` format
- [ ] Firewall allows Azure services
- [ ] Database name is correct
- [ ] Password is correct
- [ ] Port 1433 is open
- [ ] ODBC Driver 17 is installed
- [ ] Connection timeout is set appropriately

## 🚀 Quick Fix Commands

### Test Connection from Azure App Service
```bash
# SSH into your App Service
az webapp ssh --name your-app-name --resource-group your-rg

# Test connection
python -c "
import pyodbc
conn_str = 'DRIVER={ODBC Driver 17 for SQL Server};SERVER=yourserver.database.windows.net;DATABASE=yourdb;UID=youruser@yourserver;PWD=yourpass;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;'
try:
    conn = pyodbc.connect(conn_str)
    print('Connection successful!')
    conn.close()
except Exception as e:
    print(f'Connection failed: {e}')
"
```

## 📞 Next Steps

1. **Check the system test page** for detailed error information
2. **Verify your environment variables** are set correctly
3. **Test the connection** using the commands above
4. **Update firewall rules** if needed
5. **Contact Azure support** if issues persist

## 🔗 Useful Links

- [Azure SQL Database Connection Strings](https://docs.microsoft.com/en-us/azure/azure-sql/database/connect-query-python)
- [Troubleshoot Azure SQL Database Connectivity](https://docs.microsoft.com/en-us/azure/azure-sql/database/troubleshoot-connectivity-issues)
- [Azure SQL Database Firewall Rules](https://docs.microsoft.com/en-us/azure/azure-sql/database/firewall-configure)
