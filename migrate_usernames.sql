-- SQL script to migrate usernames to User foreign keys

-- Step 1: Drop the indexes that depend on the columns we're modifying
DROP INDEX contract_assigned_idx ON contracts_contract;
GO

-- Step 2: Add new columns for the foreign keys
ALTER TABLE contracts_contract ADD assigned_user_new INT NULL;
ALTER TABLE contracts_contract ADD reviewed_by_new INT NULL;
GO

-- Step 3: Add foreign key constraints
ALTER TABLE contracts_contract ADD CONSTRAINT FK_assigned_user_new FOREIGN KEY (assigned_user_new) REFERENCES auth_user(id);
ALTER TABLE contracts_contract ADD CONSTRAINT FK_reviewed_by_new FOREIGN KEY (reviewed_by_new) REFERENCES auth_user(id);
GO

-- Step 4: Update the foreign key columns with User IDs based on usernames
UPDATE contracts_contract
SET assigned_user_new = auth_user.id
FROM auth_user
WHERE contracts_contract.assigned_user_old = auth_user.username;

UPDATE contracts_contract
SET reviewed_by_new = auth_user.id
FROM auth_user
WHERE contracts_contract.reviewed_by_old = auth_user.username;
GO

-- Step 5: Drop the old columns and rename the new ones
-- First, drop the old columns
ALTER TABLE contracts_contract DROP COLUMN assigned_user_old;
ALTER TABLE contracts_contract DROP COLUMN reviewed_by_old;
GO

-- Step 6: Recreate the indexes on the new columns
CREATE INDEX contract_assigned_idx ON contracts_contract(assigned_user);
GO 