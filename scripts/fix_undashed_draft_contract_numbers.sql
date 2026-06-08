-- =============================================================================
-- Fix: Normalize undashed DLA contract numbers in intake_draftcontract
--
-- DIBBS-injected drafts were stored without dashes (e.g. SPE7L126P7653).
-- The canonical format in contracts.Contract and SharePoint is dashed
-- (e.g. SPE7L1-26-P-7653). This script:
--   1. Rewrites contract_number to dashed format using the same positional
--      rule as normalize_contract_number() in intake/pdf_parser.py:
--        chars 1-6  → prefix  (e.g. SPE7L1)
--        chars 7-8  → year    (e.g. 26)
--        char  9    → type    (e.g. P)
--        chars 10+  → seq     (e.g. 7653)
--      Result: SPE7L1-26-P-7653
--   2. Resets sharepoint_folder_status to 'pending' so the Scan SP job
--      re-probes with the corrected folder name.
--   3. Removes the stale data['sharepoint_folder_path'] JSON key so no
--      incorrect cached path is carried forward.
--
-- Run this directly against the database (not via Django migration).
-- Always run the SELECT preview first in a transaction before applying.
-- Target DB: PostgreSQL (uses jsonb - operator and ~ regex operator).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- STEP 1 — Preview: inspect all rows that will be affected before applying.
-- Run this first. Verify the normalized_number column looks correct.
-- -----------------------------------------------------------------------------
SELECT
    id,
    contract_number AS current_number,
    contract_type,
    sharepoint_folder_status,
    -- T-SQL uses '+' for concatenation and SUBSTRING(expression, start, length)
    UPPER(SUBSTRING(contract_number, 1, 6)) + '-' +
    UPPER(SUBSTRING(contract_number, 7, 2)) + '-' +
    UPPER(SUBSTRING(contract_number, 9, 1)) + '-' +
    UPPER(SUBSTRING(contract_number, 10, 4)) AS normalized_number
FROM 
    intake_draftcontract
WHERE
    LEN(contract_number) = 13
    AND contract_number LIKE '[A-Za-z][A-Za-z][A-Za-z][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9]'
    AND contract_number NOT LIKE '%-%';

    
-- -----------------------------------------------------------------------------
-- STEP 2 — Apply the fix.
-- Only run after verifying STEP 1 output looks correct.
-- -----------------------------------------------------------------------------
UPDATE intake_draftcontract
SET
    -- 1. Fixed string concatenation
    contract_number = 
        UPPER(SUBSTRING(contract_number, 1, 6)) + '-' +
        UPPER(SUBSTRING(contract_number, 7, 2)) + '-' +
        UPPER(SUBSTRING(contract_number, 9, 1)) + '-' +
        UPPER(SUBSTRING(contract_number, 10, 4)),

    sharepoint_folder_status = 'pending',

    -- 2. Fixed JSON key deletion (Assumes 'data' is an NVARCHAR(MAX) containing JSON)
    data = JSON_MODIFY(data, '$.sharepoint_folder_path', NULL),

    -- 3. Fixed current timestamp function
    modified_at = GETDATE()
WHERE
    -- 4. Fixed length and regex logic
    LEN(contract_number) = 13
    AND contract_number LIKE '[A-Za-z][A-Za-z][A-Za-z][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9]'
    AND contract_number NOT LIKE '%-%';


-- -----------------------------------------------------------------------------
-- STEP 3 — Verify: should return 0 rows if the update succeeded.
-- -----------------------------------------------------------------------------
SELECT COUNT(*) AS remaining_undashed
FROM intake_draftcontract
WHERE
    LEN(contract_number) = 13
    AND contract_number LIKE '[A-Za-z][A-Za-z][A-Za-z][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9]'
    AND contract_number NOT LIKE '%-%';
