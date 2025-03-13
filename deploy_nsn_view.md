# NSN View Conversion Deployment Plan

This document outlines the steps needed to convert the `nsn_view` from a table created by a stored procedure to a true SQL view.

## Pre-Deployment Tasks

1. **Create a full database backup**
   ```sql
   BACKUP DATABASE [YourDatabase] TO DISK = 'C:\Backups\YourDatabase_BeforeNsnViewChange.bak'
   ```

2. **Identify any code that might be writing to nsn_view**
   - Search codebase for `NsnView.objects.create`
   - Search codebase for `NsnView.objects.update`
   - Search codebase for `NsnView.objects.delete`
   - Check for any raw SQL that might be writing to nsn_view

3. **Identify SQL jobs that refresh the view**
   ```sql
   -- Check for SQL Agent jobs that call sp_RefreshNsnView
   SELECT 
       j.name AS job_name,
       js.step_id,
       js.step_name,
       js.command
   FROM 
       msdb.dbo.sysjobs j
       INNER JOIN msdb.dbo.sysjobsteps js ON j.job_id = js.job_id
   WHERE 
       js.command LIKE '%sp_RefreshNsnView%';
   ```

## Deployment Steps

1. **Deploy the updated files**
   - Update `contracts/models.py` - NsnView model documentation
   - Update `contracts/management/commands/refresh_nsn_view.py` - Deprecate refresh command
   - Remove any SQL jobs that call sp_RefreshNsnView (identified in pre-deployment)

2. **Execute the SQL script to create the view**
   ```bash
   # Using sqlcmd
   sqlcmd -S YourServer -d YourDatabase -i create_nsn_view.sql
   
   # Or run the script directly in SSMS
   ```

3. **Remove the refresh SQL Agent job (if it exists)**
   ```sql
   -- Find the job
   SELECT name FROM msdb.dbo.sysjobs WHERE name LIKE '%RefreshNsn%';
   
   -- Delete the job (replace 'JobName' with the actual name)
   USE msdb;
   EXEC dbo.sp_delete_job @job_name = N'JobName', @delete_unused_schedule = 1;
   ```

4. **Verify the view was created correctly**
   ```sql
   SELECT TOP 10 * FROM nsn_view;
   ```

## Post-Deployment Verification

1. **Test the Django management command**
   ```bash
   python manage.py refresh_nsn_view --verbose
   ```
   The command should display a deprecation warning and view statistics.

2. **Verify application functionality**
   - Check any pages that display NSN data
   - Verify the NSN search functionality works
   - Verify any reports using NSN data

3. **Monitor performance**
   - Watch for any slow queries referencing nsn_view
   - Consider creating indexed views if performance is an issue

## Rollback Plan

If issues are encountered:

1. **Revert to the table version**
   ```sql
   -- Drop the view
   DROP VIEW nsn_view;
   
   -- Run the original stored procedure that creates the table
   EXEC create_nsn_view_table;
   ```

2. **Revert code changes**
   - Revert changes to models.py
   - Revert changes to refresh_nsn_view.py

3. **Recreate any SQL Agent jobs that were removed**
   - Use the backup information from pre-deployment step 3 