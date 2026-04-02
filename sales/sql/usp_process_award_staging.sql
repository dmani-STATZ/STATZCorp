-- ============================================================
-- usp_process_award_staging
-- Processes one staging run identified by @stage_id.
-- Called from Python after bulk insert to dibbs_award_staging.
-- ============================================================
CREATE OR ALTER PROCEDURE usp_process_award_staging
    @stage_id UNIQUEIDENTIFIER
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @batch_id INT;
    DECLARE @awards_created INT = 0;
    DECLARE @faux_created INT = 0;
    DECLARE @faux_upgraded INT = 0;
    DECLARE @mods_created INT = 0;
    DECLARE @mods_skipped INT = 0;

    -- Get batch_id for this stage run
    SELECT TOP 1 @batch_id = batch_id
    FROM dibbs_award_staging
    WHERE stage_id = @stage_id;

    IF @batch_id IS NULL
    BEGIN
        DECLARE @stage_id_str VARCHAR(36) = CONVERT(VARCHAR(36), @stage_id);
        RAISERROR('No staging rows found for stage_id %s', 16, 1, @stage_id_str);
        RETURN;
    END

    BEGIN TRANSACTION;

    -- --------------------------------------------------------
    -- Step 1: Move malformed rows to error table
    -- Malformed = missing award_basic_number
    -- --------------------------------------------------------
    INSERT INTO dibbs_award_staging_errors (
        stage_id, batch_id, staged_at,
        raw_award_basic_number, raw_nsn,
        raw_delivery_order_number, error_reason
    )
    SELECT
        stage_id, batch_id, staged_at,
        award_basic_number, nsn,
        delivery_order_number,
        'Missing award_basic_number'
    FROM dibbs_award_staging
    WHERE stage_id = @stage_id
      AND (award_basic_number IS NULL OR LTRIM(RTRIM(award_basic_number)) = '');

    DELETE FROM dibbs_award_staging
    WHERE stage_id = @stage_id
      AND (award_basic_number IS NULL OR LTRIM(RTRIM(award_basic_number)) = '');

    -- --------------------------------------------------------
    -- Step 2: Classify AWARD vs MOD
    -- --------------------------------------------------------
    UPDATE dibbs_award_staging
    SET row_type = CASE
        WHEN last_mod_posting_date IS NULL
          OR LTRIM(RTRIM(last_mod_posting_date)) = '' THEN 'AWARD'
        ELSE 'MOD'
    END
    WHERE stage_id = @stage_id;

    -- --------------------------------------------------------
    -- Step 3: Dedup within staging — last row wins per
    -- business key within this stage run
    -- --------------------------------------------------------
    DELETE s1
    FROM dibbs_award_staging s1
    INNER JOIN dibbs_award_staging s2
        ON s1.stage_id = s2.stage_id
        AND s1.award_basic_number = s2.award_basic_number
        AND ISNULL(s1.delivery_order_number, '') = ISNULL(s2.delivery_order_number, '')
        AND ISNULL(s1.nsn, '') = ISNULL(s2.nsn, '')
        AND ISNULL(s1.purchase_request, '') = ISNULL(s2.purchase_request, '')
        AND s1.id < s2.id  -- keep highest id (last row wins)
    WHERE s1.stage_id = @stage_id;

    -- --------------------------------------------------------
    -- Step 4: Solicitation matching — set-based UPDATE
    -- on staging before touching production tables
    -- --------------------------------------------------------
    UPDATE s
    SET s.solicitation_id = sol.id
    FROM dibbs_award_staging s
    INNER JOIN dibbs_solicitation sol
        ON sol.solicitation_number = s.dibbs_solicitation_number
        AND sol.status <> 'NO_BID'
    WHERE s.stage_id = @stage_id
      AND s.dibbs_solicitation_number IS NOT NULL
      AND s.dibbs_solicitation_number <> '';

    -- --------------------------------------------------------
    -- Step 5: Process AWARD rows
    -- Insert new awards; upgrade existing faux awards
    -- --------------------------------------------------------

    -- 5a: Upgrade faux awards where real award now exists
    UPDATE da
    SET
        da.is_faux = 0,
        da.award_date = TRY_CONVERT(DATE, s.award_date, 110),
        da.total_contract_price = TRY_CONVERT(DECIMAL(13,5),
            REPLACE(REPLACE(REPLACE(s.total_contract_price, '$', ''), ',', ''), ' ', '')),
        da.awardee_cage = LEFT(ISNULL(s.awardee_cage, ''), 10),
        da.nomenclature = s.nomenclature,
        da.purchase_request = s.purchase_request,
        da.dibbs_solicitation_number = s.dibbs_solicitation_number,
        da.sol_number = LEFT(ISNULL(s.dibbs_solicitation_number,
                        ISNULL(s.award_basic_number, '')), 50),
        da.solicitation_id = s.solicitation_id,
        da.aw_file_date = TRY_CONVERT(DATE, s.aw_file_date, 110),
        da.aw_import_batch_id = @batch_id,
        da.we_won = CASE 
                        WHEN EXISTS (
                            SELECT 1 FROM dibbs_company_cage cc 
                            WHERE cc.cage_code = LEFT(ISNULL(s.awardee_cage, ''), 10)
                            AND cc.is_active = 1
                        ) THEN 1 
                        ELSE 0 
                    END
    FROM dibbs_award da
    INNER JOIN dibbs_award_staging s
        ON s.award_basic_number = da.award_basic_number
        AND ISNULL(s.delivery_order_number, '') = ISNULL(da.delivery_order_number, '')
        AND ISNULL(s.nsn, '') = ISNULL(da.nsn, '')
        AND ISNULL(s.purchase_request, '') = ISNULL(da.purchase_request, '')
    WHERE s.stage_id = @stage_id
      AND s.row_type = 'AWARD'
      AND da.is_faux = 1;

    SET @faux_upgraded = @@ROWCOUNT;

    -- 5b: Insert new award rows that don't exist at all
    INSERT INTO dibbs_award (
        notice_id, source, award_basic_number, delivery_order_number,
        delivery_order_counter, last_mod_posting_date, awardee_cage,
        total_contract_price, award_date, posted_date, nsn, nomenclature,
        purchase_request, dibbs_solicitation_number, sol_number,
        solicitation_id, is_faux, aw_file_date, aw_import_batch_id, we_won
    )
    SELECT
        s.notice_id,
        'DIBBS_FILE',
        s.award_basic_number,
        ISNULL(s.delivery_order_number, ''),
        s.delivery_order_counter,
        NULL,
        LEFT(ISNULL(s.awardee_cage, ''), 10),
        TRY_CONVERT(DECIMAL(13,5),
            REPLACE(REPLACE(REPLACE(s.total_contract_price, '$', ''), ',', ''), ' ', '')),
        TRY_CONVERT(DATE, s.award_date, 110),
        TRY_CONVERT(DATE, s.posted_date, 110),
        s.nsn,
        s.nomenclature,
        s.purchase_request,
        s.dibbs_solicitation_number,
        LEFT(ISNULL(s.dibbs_solicitation_number,
             ISNULL(s.award_basic_number, '')), 50),
        s.solicitation_id,
        0,
        TRY_CONVERT(DATE, s.aw_file_date, 110),
        @batch_id,
        CASE 
            WHEN EXISTS (
                SELECT 1 FROM dibbs_company_cage cc 
                WHERE cc.cage_code = LEFT(ISNULL(s.awardee_cage, ''), 10)
                AND cc.is_active = 1
            ) THEN 1 
            ELSE 0 
        END
    FROM dibbs_award_staging s
    WHERE s.stage_id = @stage_id
      AND s.row_type = 'AWARD'
      AND NOT EXISTS (
          SELECT 1 FROM dibbs_award da
          WHERE da.award_basic_number = s.award_basic_number
            AND ISNULL(da.delivery_order_number, '') = ISNULL(s.delivery_order_number, '')
            AND ISNULL(da.nsn, '') = ISNULL(s.nsn, '')
            AND ISNULL(da.purchase_request, '') = ISNULL(s.purchase_request, '')
      );

    SET @awards_created = @@ROWCOUNT;

    -- --------------------------------------------------------
    -- Step 6: Synthesize faux awards for orphaned MOD rows
    -- MOD rows with no matching award in dibbs_award yet
    -- --------------------------------------------------------
    INSERT INTO dibbs_award (
        notice_id, source, award_basic_number, delivery_order_number,
        delivery_order_counter, last_mod_posting_date, awardee_cage,
        total_contract_price, award_date, posted_date, nsn, nomenclature,
        purchase_request, dibbs_solicitation_number, sol_number,
        solicitation_id, is_faux, aw_file_date, aw_import_batch_id, we_won
    )
    SELECT DISTINCT
        s.notice_id,
        'DIBBS_FILE',
        s.award_basic_number,
        ISNULL(s.delivery_order_number, ''),
        s.delivery_order_counter,
        NULL,
        LEFT(ISNULL(s.awardee_cage, ''), 10),
        NULL,  -- faux has no price
        -- Fiscal year end derived from award_basic_number chars 7-8
        COALESCE(
            TRY_CONVERT(DATE,
                CONCAT('20', SUBSTRING(s.award_basic_number, 7, 2), '-09-30')),
            TRY_CONVERT(DATE, s.aw_file_date, 110)  -- fallback to file date
        ),
        NULL,
        s.nsn,
        s.nomenclature,
        s.purchase_request,
        s.dibbs_solicitation_number,
        LEFT(ISNULL(s.dibbs_solicitation_number,
             ISNULL(s.award_basic_number, '')), 50),
        s.solicitation_id,
        1,  -- is_faux = True
        TRY_CONVERT(DATE, s.aw_file_date, 110),
        @batch_id, 
        0
    FROM dibbs_award_staging s
    WHERE s.stage_id = @stage_id
      AND s.row_type = 'MOD'
      AND NOT EXISTS (
          SELECT 1 FROM dibbs_award da
          WHERE da.award_basic_number = s.award_basic_number
            AND ISNULL(da.delivery_order_number, '') = ISNULL(s.delivery_order_number, '')
            AND ISNULL(da.nsn, '') = ISNULL(s.nsn, '')
            AND ISNULL(da.purchase_request, '') = ISNULL(s.purchase_request, '')
      );

    SET @faux_created = @@ROWCOUNT;

    -- --------------------------------------------------------
    -- Step 7: Process MOD rows into dibbs_award_mod
    -- Skip rows that already exist on dedup key
    -- --------------------------------------------------------
    INSERT INTO dibbs_award_mod (
        award_id, award_basic_number, delivery_order_number,
        delivery_order_counter, nsn, nomenclature, awardee_cage,
        mod_date, mod_contract_price, posted_date, purchase_request,
        dibbs_solicitation_number, sol_number, aw_file_date
    )
    SELECT
        da.id,
        s.award_basic_number,
        ISNULL(s.delivery_order_number, ''),
        s.delivery_order_counter,
        s.nsn,
        s.nomenclature,
        LEFT(ISNULL(s.awardee_cage, ''), 10),
        TRY_CONVERT(DATE, s.last_mod_posting_date, 110),
        TRY_CONVERT(DECIMAL(13,5),
            REPLACE(REPLACE(REPLACE(s.total_contract_price, '$', ''), ',', ''), ' ', '')),
        TRY_CONVERT(DATE, s.posted_date, 110),
        s.purchase_request,
        s.dibbs_solicitation_number,
        LEFT(ISNULL(s.dibbs_solicitation_number,
             ISNULL(s.award_basic_number, '')), 50),
        TRY_CONVERT(DATE, s.aw_file_date, 110)
    FROM dibbs_award_staging s
    INNER JOIN dibbs_award da
        ON da.award_basic_number = s.award_basic_number
        AND ISNULL(da.delivery_order_number, '') = ISNULL(s.delivery_order_number, '')
        AND ISNULL(da.nsn, '') = ISNULL(s.nsn, '')
        AND ISNULL(da.purchase_request, '') = ISNULL(s.purchase_request, '')
    WHERE s.stage_id = @stage_id
      AND s.row_type = 'MOD'
      AND NOT EXISTS (
          SELECT 1 FROM dibbs_award_mod m
          WHERE m.award_id = da.id
            AND m.mod_date = TRY_CONVERT(DATE, s.last_mod_posting_date, 110)
            AND ISNULL(m.nsn, '') = ISNULL(s.nsn, '')
            AND ISNULL(CAST(m.mod_contract_price AS VARCHAR(20)), '') =
                ISNULL(REPLACE(REPLACE(REPLACE(
                    s.total_contract_price, '$', ''), ',', ''), ' ', ''), '')
            AND ISNULL(m.purchase_request, '') = ISNULL(s.purchase_request, '')
      );

    SET @mods_created = @@ROWCOUNT;

    -- Count skipped mods
    SELECT @mods_skipped = COUNT(*)
    FROM dibbs_award_staging s
    INNER JOIN dibbs_award da
        ON da.award_basic_number = s.award_basic_number
        AND ISNULL(da.delivery_order_number, '') = ISNULL(s.delivery_order_number, '')
        AND ISNULL(da.nsn, '') = ISNULL(s.nsn, '')
        AND ISNULL(da.purchase_request, '') = ISNULL(s.purchase_request, '')
    WHERE s.stage_id = @stage_id
      AND s.row_type = 'MOD'
      AND EXISTS (
          SELECT 1 FROM dibbs_award_mod m
          WHERE m.award_id = da.id
            AND m.mod_date = TRY_CONVERT(DATE, s.last_mod_posting_date, 110)
            AND ISNULL(m.nsn, '') = ISNULL(s.nsn, '')
            AND ISNULL(CAST(m.mod_contract_price AS VARCHAR(20)), '') =
                ISNULL(REPLACE(REPLACE(REPLACE(
                    s.total_contract_price, '$', ''), ',', ''), ' ', ''), '')
            AND ISNULL(m.purchase_request, '') = ISNULL(s.purchase_request, '')
      );

    -- --------------------------------------------------------
    -- Step 8: Update batch counters
    -- --------------------------------------------------------
    UPDATE dibbs_award_import_batch
    SET
        awards_created = awards_created + @awards_created,
        faux_created   = faux_created   + @faux_created,
        faux_upgraded  = faux_upgraded  + @faux_upgraded,
        mods_created   = mods_created   + @mods_created,
        mods_skipped   = mods_skipped   + @mods_skipped
    WHERE id = @batch_id;

    -- --------------------------------------------------------
    -- Step 9: Clear staging rows for this run only
    -- --------------------------------------------------------
    DELETE FROM dibbs_award_staging
    WHERE stage_id = @stage_id;

    COMMIT TRANSACTION;
END;
