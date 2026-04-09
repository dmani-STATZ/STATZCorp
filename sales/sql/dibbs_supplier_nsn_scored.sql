-- dibbs_supplier_nsn_scored
-- Live computed match score view for SupplierNSN records.
-- Deploy via SSMS using CREATE OR ALTER VIEW.
-- DO NOT run via Django migrations or management commands.
-- Score = 1.0 (manual entry bonus) + sum of contract history weights:
--   <= 2 years:  1.0 per contract
--   <= 4 years:  0.75 per contract
--   >  4 years:  0.5 per contract

CREATE OR ALTER VIEW [dbo].[dibbs_supplier_nsn_scored] AS
SELECT
    n.[id],
    n.[supplier_id],
    n.[nsn],
    1.0 + ISNULL(
        (
            SELECT SUM(
                CASE
                    WHEN DATEDIFF(DAY, c.[award_date], GETDATE()) <= 730  THEN 1.0
                    WHEN DATEDIFF(DAY, c.[award_date], GETDATE()) <= 1460 THEN 0.75
                    ELSE 0.5
                END
            )
            FROM [dbo].[contracts_clin] cl
            INNER JOIN [dbo].[contracts_contract] c ON c.[id] = cl.[contract_id]
            INNER JOIN [dbo].[contracts_nsn] cn ON cn.[id] = cl.[nsn_id]
            WHERE cl.[supplier_id] = n.[supplier_id]
              AND cn.[nsn_code] = n.[nsn]
              AND c.[award_date] IS NOT NULL
        ),
    0) AS [match_score]
FROM [dbo].[dibbs_supplier_nsn] n;
