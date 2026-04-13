-- dibbs_supplier_nsn_scored
-- Live computed match score view for SupplierNSN records.
-- Deploy via SSMS using CREATE OR ALTER VIEW.
-- DO NOT run via Django migrations or management commands.
-- Score = 1.0 (manual entry bonus) + sum of contract history weights:
--   <= 2 years:  1.0 per contract
--   <= 4 years:  0.75 per contract
--   >  4 years:  0.5 per contract

CREATE OR ALTER VIEW [dbo].[dibbs_supplier_nsn_scored] AS
SELECT        ROW_NUMBER() OVER (ORDER BY combined.supplier_id, combined.nsn) AS [id], combined.supplier_id, combined.nsn, SUM(combined.score) AS match_score
FROM            (/* Query 1: Contract history (won contracts only)*/ SELECT cl.[supplier_id], REPLACE(cn.[nsn_code], '-', '') AS [nsn], CASE WHEN DATEDIFF(DAY, c.[award_date], GETDATE()) <= 730 THEN 1.0 WHEN DATEDIFF(DAY,
                                                    c.[award_date], GETDATE()) <= 1460 THEN 0.75 ELSE 0.5 END AS [score]
                          FROM            [dbo].[contracts_clin] cl INNER JOIN
                                                    [dbo].[contracts_contract] c ON c.[id] = cl.[contract_id] INNER JOIN
                                                    [dbo].[contracts_nsn] cn ON cn.[id] = cl.[nsn_id] INNER JOIN
                                                    [dbo].[contracts_supplier] s ON s.[id] = cl.[supplier_id]
                          WHERE        c.[award_date] IS NOT NULL AND cl.[supplier_id] IS NOT NULL AND cl.[nsn_id] IS NOT NULL AND s.[archived] = 0
                          UNION ALL
                          /* Query 2: Manual confirmation bonus*/ SELECT n.[supplier_id], n.[nsn], 1.0 AS [score]
                          FROM            [dbo].[dibbs_supplier_nsn] n INNER JOIN
                                                   [dbo].[contracts_supplier] s ON s.[id] = n.[supplier_id]
                          WHERE        s.[archived] = 0) combined
GROUP BY combined.[supplier_id], combined.[nsn]
