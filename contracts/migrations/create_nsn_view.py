from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ('contracts', 'create_clin_view'),  # Make sure this depends on the previous migration
    ]

    operations = [
        # Create the nsn_view table directly
        migrations.RunSQL(
            """
            -- Create the table if it doesn't exist
            IF OBJECT_ID('nsn_view', 'U') IS NULL
            BEGIN
                CREATE TABLE nsn_view (
                    id INT PRIMARY KEY,
                    nsn_code NVARCHAR(20) NULL,
                    description NVARCHAR(MAX) NULL,
                    part_number NVARCHAR(25) NULL,
                    revision NVARCHAR(25) NULL,
                    notes NVARCHAR(MAX) NULL,
                    directory_url NVARCHAR(200) NULL,
                    clin_count INT NULL,
                    search_vector NVARCHAR(MAX) NULL
                );
            END
            """,
            "IF OBJECT_ID('nsn_view', 'U') IS NOT NULL DROP TABLE nsn_view;"
        ),
        
        # Create index on nsn_code (but not on search_vector as it's NVARCHAR(MAX))
        migrations.RunSQL(
            """
            -- Create index on nsn_code
            IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'nsn_view_code_idx' AND object_id = OBJECT_ID('nsn_view'))
                CREATE INDEX nsn_view_code_idx ON nsn_view (nsn_code);
            
            -- Note: We cannot create an index on search_vector because it's NVARCHAR(MAX)
            -- For searching this column, use LIKE or CONTAINS operators, or set up full-text search
            """,
            """
            -- Drop index
            IF EXISTS (SELECT * FROM sys.indexes WHERE name = 'nsn_view_code_idx' AND object_id = OBJECT_ID('nsn_view'))
                DROP INDEX nsn_view_code_idx ON nsn_view;
            """
        ),
        
        # Populate the nsn_view table with initial data
        migrations.RunSQL(
            """
            -- Clear existing data
            TRUNCATE TABLE nsn_view;
            
            -- Insert data into the materialized view
            INSERT INTO nsn_view (
                id, 
                nsn_code, 
                description, 
                part_number, 
                revision, 
                notes, 
                directory_url,
                clin_count,
                search_vector
            )
            SELECT 
                n.id,
                n.nsn_code,
                n.description,
                n.part_number,
                n.revision,
                n.notes,
                n.directory_url,
                (SELECT COUNT(*) FROM contracts_clin c WHERE c.nsn_id = n.id) AS clin_count,
                -- Create a concatenated search vector for faster text search
                CONCAT(
                    ISNULL(n.nsn_code, ''), ' ',
                    ISNULL(n.description, ''), ' ',
                    ISNULL(n.part_number, ''), ' ',
                    ISNULL(n.revision, '')
                ) AS search_vector
            FROM 
                contracts_nsn n;
            """,
            "-- No reverse SQL needed for data population"
        ),
        
        # Create a stored procedure to refresh the view
        migrations.RunSQL(
            """
            -- Create a stored procedure for refreshing the view
            CREATE OR ALTER PROCEDURE dbo.sp_RefreshNsnView
            AS
            BEGIN
                -- Clear existing data
                TRUNCATE TABLE nsn_view;
                
                -- Insert data into the materialized view
                INSERT INTO nsn_view (
                    id, 
                    nsn_code, 
                    description, 
                    part_number, 
                    revision, 
                    notes, 
                    directory_url,
                    clin_count,
                    search_vector
                )
                SELECT 
                    n.id,
                    n.nsn_code,
                    n.description,
                    n.part_number,
                    n.revision,
                    n.notes,
                    n.directory_url,
                    (SELECT COUNT(*) FROM contracts_clin c WHERE c.nsn_id = n.id) AS clin_count,
                    -- Create a concatenated search vector for faster text search
                    CONCAT(
                        ISNULL(n.nsn_code, ''), ' ',
                        ISNULL(n.description, ''), ' ',
                        ISNULL(n.part_number, ''), ' ',
                        ISNULL(n.revision, '')
                    ) AS search_vector
                FROM 
                    contracts_nsn n;
            END;
            """,
            "DROP PROCEDURE IF EXISTS dbo.sp_RefreshNsnView;"
        ),
        
        # Note: SQL Agent job creation is typically done outside of migrations
        # as it requires special permissions and is environment-specific
        migrations.RunSQL(
            """
            -- The following is a template for creating a SQL Agent job
            -- This should be executed manually by a DBA with appropriate permissions
            /*
            USE msdb;
            
            -- Delete the job if it exists
            IF EXISTS (SELECT * FROM msdb.dbo.sysjobs WHERE name = N'Refresh NSN View')
            BEGIN
                EXEC msdb.dbo.sp_delete_job @job_name = N'Refresh NSN View';
            END
            
            -- Create the job
            EXEC msdb.dbo.sp_add_job
                @job_name = N'Refresh NSN View',
                @description = N'Refreshes the materialized view for NSN data',
                @category_name = N'Database Maintenance',
                @owner_login_name = N'sa';
                
            -- Add a job step
            EXEC msdb.dbo.sp_add_jobstep
                @job_name = N'Refresh NSN View',
                @step_name = N'Refresh NSN View',
                @subsystem = N'TSQL',
                @command = N'EXEC dbo.sp_RefreshNsnView',
                @database_name = DB_NAME();
                
            -- Add a schedule
            EXEC msdb.dbo.sp_add_jobschedule
                @job_name = N'Refresh NSN View',
                @name = N'Daily at midnight',
                @freq_type = 4, -- Daily
                @freq_interval = 1, -- Every day
                @active_start_time = 000000; -- 12:00 AM
                
            -- Add a server
            EXEC msdb.dbo.sp_add_jobserver
                @job_name = N'Refresh NSN View';
            */
            """,
            """
            -- No reverse SQL needed for the comment
            """
        )
    ] 