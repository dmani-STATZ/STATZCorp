-- ============================================================
-- Fix: strip trailing DIBBS U+00BB HTML artifact from
-- award_basic_number and delivery_order_number in:
--   dibbs_award_mod  (primary target — causes matched_contract = NULL)
--   dibbs_award      (secondary target — data consistency)
--
-- Run in SSMS against the STATZWeb database.
-- Execute the SELECT preview blocks first, then the UPDATE blocks.
-- ============================================================

-- ── STEP 1: Preview dibbs_award_mod dirty rows ──────────────
SELECT
    id,
    award_basic_number,
    delivery_order_number,
    mod_date,
    matched_contract_id
FROM dibbs_award_mod
WHERE award_basic_number    LIKE N'%' + NCHAR(0x00BB) + N'%'
   OR delivery_order_number LIKE N'%' + NCHAR(0x00BB) + N'%'
ORDER BY mod_date DESC;

-- ── STEP 2: Clean dibbs_award_mod ───────────────────────────
UPDATE dibbs_award_mod
SET
    award_basic_number = RTRIM(
        CASE WHEN CHARINDEX(NCHAR(0x00BB), award_basic_number) > 0
             THEN LEFT(award_basic_number, CHARINDEX(NCHAR(0x00BB), award_basic_number) - 1)
             ELSE award_basic_number
        END
    ),
    delivery_order_number = RTRIM(
        CASE WHEN CHARINDEX(NCHAR(0x00BB), delivery_order_number) > 0
             THEN LEFT(delivery_order_number, CHARINDEX(NCHAR(0x00BB), delivery_order_number) - 1)
             ELSE delivery_order_number
        END
    )
WHERE award_basic_number    LIKE N'%' + NCHAR(0x00BB) + N'%'
   OR delivery_order_number LIKE N'%' + NCHAR(0x00BB) + N'%';

-- ── STEP 3: Preview dibbs_award dirty rows ──────────────────
SELECT
    id,
    award_basic_number,
    delivery_order_number,
    award_date
FROM dibbs_award
WHERE award_basic_number    LIKE N'%' + NCHAR(0x00BB) + N'%'
   OR delivery_order_number LIKE N'%' + NCHAR(0x00BB) + N'%'
ORDER BY award_date DESC;

-- ── STEP 4: Clean dibbs_award ───────────────────────────────
UPDATE dibbs_award
SET
    award_basic_number = RTRIM(
        CASE WHEN CHARINDEX(NCHAR(0x00BB), award_basic_number) > 0
             THEN LEFT(award_basic_number, CHARINDEX(NCHAR(0x00BB), award_basic_number) - 1)
             ELSE award_basic_number
        END
    ),
    delivery_order_number = RTRIM(
        CASE WHEN CHARINDEX(NCHAR(0x00BB), delivery_order_number) > 0
             THEN LEFT(delivery_order_number, CHARINDEX(NCHAR(0x00BB), delivery_order_number) - 1)
             ELSE delivery_order_number
        END
    )
WHERE award_basic_number    LIKE N'%' + NCHAR(0x00BB) + N'%'
   OR delivery_order_number LIKE N'%' + NCHAR(0x00BB) + N'%';

-- ── STEP 5: Verify — both queries must return 0 rows ────────
SELECT COUNT(*) AS remaining_dirty_mods  FROM dibbs_award_mod
WHERE award_basic_number LIKE N'%' + NCHAR(0x00BB) + N'%'
   OR delivery_order_number LIKE N'%' + NCHAR(0x00BB) + N'%';

SELECT COUNT(*) AS remaining_dirty_awards FROM dibbs_award
WHERE award_basic_number LIKE N'%' + NCHAR(0x00BB) + N'%'
   OR delivery_order_number LIKE N'%' + NCHAR(0x00BB) + N'%';

-- ── STEP 6: Re-match previously-unmatched mods ──────────────
-- Now that award_basic_number is clean, mods that previously had
-- matched_contract = NULL due to the artifact can be matched.
-- This joins on the dashed canonical format stored in contracts_contract.
--
-- NOTE: contracts_contract.contract_number is stored in dashed format
-- e.g. 'SPE4A6-26-F-Z3PY'. The cleaned award_basic_number is undashed
-- e.g. 'SPE4A626FZ3PY'. The normalization happens in Python — run the
-- Django management command below instead of doing it in raw SQL.
--
-- After running Steps 1-5 above, execute from the repo root:
--
--   python manage.py shell -c "
--   from sales.services.contract_mods import rematch_unmatched_mods
--   rematch_unmatched_mods()
--   "
--
-- If rematch_unmatched_mods() does not exist yet, see Step 5 of the
-- Cursor prompt which adds it.
