-- SQL Server script to migrate notes from STATZ_NOTES_TBL to the new ContentType-based Note table
-- Run this in SQL Server Management Studio

-- First, let's determine the ContentType IDs for Contract and Clin
-- You'll need to replace these values with the actual ContentType IDs from your Django database
-- You can get these by running:
-- SELECT * FROM django_content_type WHERE app_label = 'contracts' AND (model = 'contract' OR model = 'clin')

DECLARE @ContractContentTypeID INT = 18; -- REPLACE with actual ID from django_content_type
DECLARE @ClinContentTypeID INT = 12;     -- REPLACE with actual ID from django_content_type

-- Create a temporary table to hold the migrated data
CREATE TABLE #TempNotes (
    content_type_id INT,
    object_id INT,
    note NVARCHAR(MAX),
    created_by_id INT NULL,
    created_on DATETIME,
    modified_by_id INT NULL,
    modified_on DATETIME
);

-- Insert data from STATZ_NOTES_TBL into the temp table, mapping Type to content_type_id
INSERT INTO #TempNotes (content_type_id, object_id, note, created_by_id, created_on, modified_by_id, modified_on)
SELECT 
    CASE 
        WHEN Type = 'Cont' THEN @ContractContentTypeID
        WHEN Type = 'Sub' THEN @ClinContentTypeID
        ELSE NULL -- Handle any other types
    END AS content_type_id,
    Ref_ID AS object_id,
    Note AS note,
    NULL AS created_by_id, -- We'll need to handle user mapping separately
    CreatedOn AS created_on,
    NULL AS modified_by_id, -- We'll need to handle user mapping separately
    ModifiedOn AS modified_on
FROM STATZ_NOTES_TBL
WHERE Type IN ('Cont', 'Sub'); -- Only migrate Contract and Clin notes

-- Optional: Map usernames to user IDs if needed
-- This assumes you have a way to map the username strings to actual User IDs
-- You might need to adjust this based on your actual user table structure
/*
UPDATE #TempNotes
SET created_by_id = u.id
FROM #TempNotes t
JOIN auth_user u ON t.created_by = u.username;

UPDATE #TempNotes
SET modified_by_id = u.id
FROM #TempNotes t
JOIN auth_user u ON t.modified_by = u.username;
*/

-- Now insert the data into your Django Note table
-- Adjust the table name and column names if they're different in your Django setup
INSERT INTO contracts_note (content_type_id, object_id, note, created_by_id, created_on, modified_by_id, modified_on)
SELECT content_type_id, object_id, note, created_by_id, created_on, modified_by_id, modified_on
FROM #TempNotes
WHERE content_type_id IS NOT NULL; -- Skip any notes with unknown types

-- Drop the temporary table
DROP TABLE #TempNotes;

-- Print summary
SELECT 'Migration complete. ' + CAST(@@ROWCOUNT AS VARCHAR) + ' notes migrated.' AS Result; 