-- SQL script to remove old username fields after confirming data migration

-- First, verify that data was properly migrated
SELECT COUNT(*) AS total_records,
       SUM(CASE WHEN assigned_user_old IS NOT NULL AND assigned_user_id IS NULL THEN 1 ELSE 0 END) AS missing_assigned_user,
       SUM(CASE WHEN reviewed_by_old IS NOT NULL AND reviewed_by_id IS NULL THEN 1 ELSE 0 END) AS missing_reviewed_by
FROM contracts_contract;
GO

-- If the counts for missing_assigned_user and missing_reviewed_by are 0, then proceed with:

-- Drop the old columns
ALTER TABLE contracts_contract DROP COLUMN assigned_user_old;
ALTER TABLE contracts_contract DROP COLUMN reviewed_by_old;
GO 