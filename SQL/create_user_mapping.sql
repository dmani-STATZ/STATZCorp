-- Create temporary user mapping table
IF OBJECT_ID('tempdb..#UserMapping') IS NOT NULL
    DROP TABLE #UserMapping;

CREATE TABLE #UserMapping (
    user_id INT,
    username NVARCHAR(150)
);

-- Insert data from auth_user table
INSERT INTO #UserMapping (user_id, username)
SELECT id, username
FROM auth_user;

-- Insert any additional legacy usernames that need to be mapped
-- This section should be customized based on your legacy data
INSERT INTO #UserMapping (user_id, username)
SELECT DISTINCT
    u.id,
    legacy.username
FROM (
    -- Add legacy usernames from ContractLog database
    SELECT DISTINCT CreatedBy as username FROM ContractLog.dbo.STATZ_CONTRACTS_TBL WHERE CreatedBy IS NOT NULL
    UNION
    SELECT DISTINCT ModifiedBy FROM ContractLog.dbo.STATZ_CONTRACTS_TBL WHERE ModifiedBy IS NOT NULL
    UNION
    SELECT DISTINCT CreatedBy FROM ContractLog.dbo.STATZ_SUB_CONTRACTS_TBL WHERE CreatedBy IS NOT NULL
    UNION
    SELECT DISTINCT ModifiedBy FROM ContractLog.dbo.STATZ_SUB_CONTRACTS_TBL WHERE ModifiedBy IS NOT NULL
    -- Add legacy usernames from CommonCore database
    UNION
    SELECT DISTINCT CreatedBy FROM CommonCore.dbo.DATA_NOTES_TBL WHERE CreatedBy IS NOT NULL
    UNION
    SELECT DISTINCT ModifiedBy FROM CommonCore.dbo.DATA_NOTES_TBL WHERE ModifiedBy IS NOT NULL
) legacy
LEFT JOIN auth_user u ON LOWER(u.username) = LOWER(legacy.username)
WHERE u.id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 
        FROM #UserMapping m 
        WHERE m.user_id = u.id 
        AND m.username = legacy.username
    );

-- Create an index to improve lookup performance
CREATE INDEX idx_user_mapping_username ON #UserMapping (username);
CREATE INDEX idx_user_mapping_user_id ON #UserMapping (user_id);

-- Print summary of mappings
SELECT 'User mapping table created with ' + CAST(COUNT(*) AS NVARCHAR(10)) + ' entries' AS Summary
FROM #UserMapping;

-- Print any unmapped legacy users for review
SELECT DISTINCT username
FROM (
    -- Legacy usernames from ContractLog
    SELECT CreatedBy as username FROM ContractLog.dbo.STATZ_CONTRACTS_TBL WHERE CreatedBy IS NOT NULL
    UNION
    SELECT ModifiedBy FROM ContractLog.dbo.STATZ_CONTRACTS_TBL WHERE ModifiedBy IS NOT NULL
    UNION
    SELECT CreatedBy FROM ContractLog.dbo.STATZ_SUB_CONTRACTS_TBL WHERE CreatedBy IS NOT NULL
    UNION
    SELECT ModifiedBy FROM ContractLog.dbo.STATZ_SUB_CONTRACTS_TBL WHERE ModifiedBy IS NOT NULL
    -- Legacy usernames from CommonCore
    UNION
    SELECT CreatedBy FROM CommonCore.dbo.DATA_NOTES_TBL WHERE CreatedBy IS NOT NULL
    UNION
    SELECT ModifiedBy FROM CommonCore.dbo.DATA_NOTES_TBL WHERE ModifiedBy IS NOT NULL
) legacy
WHERE NOT EXISTS (
    SELECT 1 
    FROM #UserMapping m 
    WHERE m.username = legacy.username
)
ORDER BY username; 