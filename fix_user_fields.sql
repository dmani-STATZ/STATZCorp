-- SQL script to fix the user fields migration

-- Step 1: Drop the index on assigned_user if it exists
IF EXISTS (SELECT * FROM sys.indexes WHERE name = 'contract_assigned_idx' AND object_id = OBJECT_ID('contracts_contract'))
BEGIN
    DROP INDEX contract_assigned_idx ON contracts_contract;
END
GO

-- Step 2: Update the temporary foreign key fields with data from the string fields
UPDATE contracts_contract
SET assigned_user_tmp_id = auth_user.id
FROM auth_user
WHERE contracts_contract.assigned_user = auth_user.username
  AND contracts_contract.assigned_user_tmp_id IS NULL;

UPDATE contracts_contract
SET reviewed_by_tmp_id = auth_user.id
FROM auth_user
WHERE contracts_contract.reviewed_by = auth_user.username
  AND contracts_contract.reviewed_by_tmp_id IS NULL;
GO

-- Step 3: Rename the columns to match Django's model
-- First, drop the foreign key constraints
ALTER TABLE contracts_contract DROP CONSTRAINT contracts_contract_assigned_user_tmp_id_5c57058d_fk_auth_user_id;
ALTER TABLE contracts_contract DROP CONSTRAINT contracts_contract_reviewed_by_tmp_id_0c53ef16_fk_auth_user_id;
GO

-- Rename the temporary columns to the final names
EXEC sp_rename 'contracts_contract.assigned_user', 'assigned_user_old', 'COLUMN';
EXEC sp_rename 'contracts_contract.reviewed_by', 'reviewed_by_old', 'COLUMN';
EXEC sp_rename 'contracts_contract.assigned_user_tmp_id', 'assigned_user_id', 'COLUMN';
EXEC sp_rename 'contracts_contract.reviewed_by_tmp_id', 'reviewed_by_id', 'COLUMN';
GO

-- Add back the foreign key constraints with the new column names
ALTER TABLE contracts_contract ADD CONSTRAINT FK_assigned_user_id FOREIGN KEY (assigned_user_id) REFERENCES auth_user(id);
ALTER TABLE contracts_contract ADD CONSTRAINT FK_reviewed_by_id FOREIGN KEY (reviewed_by_id) REFERENCES auth_user(id);
GO

-- Step 4: Recreate the index on the new column
CREATE INDEX contract_assigned_idx ON contracts_contract(assigned_user_id);
GO 