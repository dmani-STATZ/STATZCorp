-- ============================================================
-- Hand-run AFTER deploying the contract_level_charge CLIN Fix
-- update. Updates existing ClinReclassificationLog rows that
-- used the old 'packaging' destination_type slug to the new
-- 'contract_level_charge' slug.
--
-- Safe to run multiple times (idempotent).
-- Run in SSMS or via Azure Data Studio against the target DB.
-- ============================================================
UPDATE contracts_clinreclassificationlog
SET destination_type = 'contract_level_charge'
WHERE destination_type = 'packaging';

SELECT @@ROWCOUNT AS rows_updated;
