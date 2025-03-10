-- This script should be run by a DBA with appropriate permissions
-- It sets up the materialized view for NSN data and creates a SQL Agent job
-- to refresh the view nightly (if SQL Server Agent is running)

-- Ensure the stored procedure exists
IF NOT EXISTS (SELECT * FROM sys.procedures WHERE name = 'sp_RefreshNsnView')
BEGIN
    EXEC('
    CREATE PROCEDURE dbo.sp_RefreshNsnView
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
                ISNULL(n.nsn_code, ''''), '' '',
                ISNULL(n.description, ''''), '' '',
                ISNULL(n.part_number, ''''), '' '',
                ISNULL(n.revision, '''')
            ) AS search_vector
        FROM 
            contracts_nsn n;
    END
    ');
END

-- Ensure the nsn_view table exists
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
    
    -- Create index on nsn_code
    CREATE INDEX nsn_view_code_idx ON nsn_view (nsn_code);
    
    -- Note: We cannot create an index on search_vector because it's NVARCHAR(MAX)
    -- For searching this column, use LIKE or CONTAINS operators
END

-- Add simple indexes to the NSN table
-- Note: We cannot include 'description' in an index because it's NVARCHAR(MAX)
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_nsn_code' AND object_id = OBJECT_ID('contracts_nsn'))
    CREATE INDEX idx_nsn_code ON contracts_nsn (nsn_code);

IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_nsn_part_number' AND object_id = OBJECT_ID('contracts_nsn'))
    CREATE INDEX idx_nsn_part_number ON contracts_nsn (part_number);

-- Note: For efficient searching of text columns like 'description',
-- full-text search is recommended. However, it requires SQL Server
-- with Full-Text Search installed and appropriate permissions.
--
-- If full-text search is not available, you can still search using
-- LIKE or CONTAINS operators, but performance may be slower.

-- Initial population of the nsn_view table
PRINT 'Populating the NSN view with initial data...';
EXEC dbo.sp_RefreshNsnView;
PRINT 'NSN view populated successfully.';

-- Check if SQL Server Agent is running
DECLARE @is_agent_running BIT;
BEGIN TRY
    EXEC msdb.dbo.sp_verify_job_identifiers N'@job_name', N'dummy';
    SET @is_agent_running = 1;
END TRY
BEGIN CATCH
    SET @is_agent_running = 0;
END CATCH

-- Set up SQL Agent job to refresh the NSN view nightly (if SQL Server Agent is running)
IF @is_agent_running = 1
BEGIN
    PRINT 'SQL Server Agent is running. Setting up scheduled job...';
    
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
    
    DECLARE @DBName NVARCHAR(128);
    SET @DBName = DB_NAME();
    
    -- Add a job step
    EXEC msdb.dbo.sp_add_jobstep
        @job_name = N'Refresh NSN View',
        @step_name = N'Refresh NSN View',
        @subsystem = N'TSQL',
        @command = N'EXEC dbo.sp_RefreshNsnView',
        @database_name = @DBName;
        
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
        
    PRINT 'SQL Server Agent job created successfully.';
END
ELSE
BEGIN
    PRINT '-------------------------------------------------------------------';
    PRINT 'WARNING: SQL Server Agent is not running.';
    PRINT 'The scheduled job to refresh the NSN view could not be created.';
    PRINT '';
    PRINT 'To manually refresh the NSN view, run the following command:';
    PRINT '    EXEC dbo.sp_RefreshNsnView;';
    PRINT '';
    PRINT 'You should run this command periodically, especially after:';
    PRINT '- Adding new NSN records';
    PRINT '- Updating existing NSN records';
    PRINT '- Making changes to the NSN-CLIN relationships';
    PRINT '';
    PRINT 'Alternatively, you can enable SQL Server Agent and run this script again.';
    PRINT '-------------------------------------------------------------------';
END 