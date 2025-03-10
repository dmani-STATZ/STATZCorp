# Manual Refresh of NSN View

Since SQL Server Agent is not running on your server, you'll need to manually refresh the NSN view periodically to ensure it contains up-to-date data. This document explains how to do that.

## Why Manual Refresh is Needed

The NSN view is a materialized view that contains pre-computed data from the NSN table and related tables. This view is used to improve the performance of the CLIN form by reducing the need for complex joins and calculations at runtime.

However, the view is not automatically updated when the underlying data changes. It needs to be refreshed periodically to ensure it contains the latest data.

## When to Refresh the NSN View

You should refresh the NSN view:

1. After adding new NSN records
2. After updating existing NSN records
3. After making changes to the NSN-CLIN relationships
4. Periodically (e.g., daily or weekly) to ensure the view is up-to-date

## How to Refresh the NSN View

### Option 1: Using the Django Management Command

The easiest way to refresh the NSN view is to use the Django management command:

```bash
python manage.py refresh_nsn_view
```

For more detailed output, you can use the `--verbose` flag:

```bash
python manage.py refresh_nsn_view --verbose
```

### Option 2: Using SQL Server Management Studio

If you have access to SQL Server Management Studio, you can refresh the NSN view by executing the stored procedure:

```sql
EXEC dbo.sp_RefreshNsnView;
```

### Option 3: Using sqlcmd

You can also use the sqlcmd utility to refresh the NSN view:

```bash
sqlcmd -S <server> -d <database> -U <username> -P <password> -Q "EXEC dbo.sp_RefreshNsnView;"
```

Replace `<server>`, `<database>`, `<username>`, and `<password>` with your actual values.

## Setting Up Scheduled Refresh

### Option 1: Using Windows Task Scheduler

If you're running on Windows, you can use the Task Scheduler to set up a scheduled task to refresh the NSN view:

1. Open Task Scheduler
2. Create a new task
3. Set the trigger to run daily at midnight
4. Set the action to run a program
5. Program/script: `python`
6. Arguments: `manage.py refresh_nsn_view`
7. Start in: `C:\path\to\your\project`

### Option 2: Using cron (Linux/macOS)

If you're running on Linux or macOS, you can use cron to set up a scheduled task:

```bash
# Edit the crontab
crontab -e

# Add a line to run the command daily at midnight
0 0 * * * cd /path/to/your/project && python manage.py refresh_nsn_view
```

### Option 3: Enable SQL Server Agent

If possible, the best option is to enable SQL Server Agent on your server. This will allow you to use the SQL Agent job that was set up in the initial script.

To enable SQL Server Agent:

1. Open SQL Server Configuration Manager
2. Go to SQL Server Services
3. Right-click on SQL Server Agent and select Properties
4. Set the Start Mode to Automatic
5. Click Apply and OK
6. Right-click on SQL Server Agent and select Start

After enabling SQL Server Agent, run the setup script again to create the SQL Agent job:

```bash
sqlcmd -S <server> -d <database> -U <username> -P <password> -i contracts/sql/setup_nsn_fulltext_and_job.sql
sqlcmd -S 10.103.10.220 -d STATZWeb_Dev -U statz -P STATZ57472! -i contracts/sql/setup_nsn_fulltext_and_job.sql
``` 