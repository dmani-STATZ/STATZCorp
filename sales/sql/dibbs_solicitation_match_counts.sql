-- dibbs_solicitation_match_counts
-- Live match count per solicitation — additive T1 + T2 + T3.
-- T1: row counts per NSN in dibbs_supplier_nsn_scored (tier-1 capability rows)
-- T2: row counts per NSN in dibbs_approved_source
-- T3: row counts per FSC in dibbs_supplier_fsc
-- Per solicitation line: (T1 count for that line's normalized NSN) + (T2) + (T3 for first 4 chars of normalized NSN).
-- Solicitations with multiple lines SUM those per-line totals (additive, not deduplicated — display only).
-- Deploy via SSMS using CREATE OR ALTER VIEW.
-- DO NOT run via Django migrations or management commands.

CREATE OR ALTER VIEW [dbo].[dibbs_solicitation_match_counts] AS
SELECT
    line.[solicitation_id],
    SUM(
        ISNULL(t1.[cnt], 0)
        + ISNULL(t2.[cnt], 0)
        + ISNULL(t3.[cnt], 0)
    ) AS [match_count]
FROM [dbo].[dibbs_solicitation_line] line
LEFT JOIN (
    SELECT [nsn], COUNT(*) AS [cnt]
    FROM [dbo].[dibbs_supplier_nsn_scored]
    GROUP BY [nsn]
) t1 ON t1.[nsn] = REPLACE(line.[nsn], '-', '')
LEFT JOIN (
    SELECT a.[nsn], COUNT(*) AS [cnt]
    FROM [dbo].[tbl_ApprovedSource] a
    INNER JOIN [dbo].[contracts_supplier] s 
        ON s.[cage_code] = a.[approved_cage]
        AND s.[archived] = 0
    GROUP BY a.[nsn]
) t2 ON t2.[nsn] = REPLACE(line.[nsn], '-', '')
LEFT JOIN (
    SELECT [fsc_code], COUNT(*) AS [cnt]
    FROM [dbo].[dibbs_supplier_fsc]
    GROUP BY [fsc_code]
) t3 ON t3.[fsc_code] = LEFT(REPLACE(line.[nsn], '-', ''), 4)
GROUP BY line.[solicitation_id];
