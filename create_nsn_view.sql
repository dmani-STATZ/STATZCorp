-- Drop the existing table if it exists
IF OBJECT_ID('nsn_view', 'U') IS NOT NULL
    DROP TABLE nsn_view;
GO

-- Drop the view if it exists
IF OBJECT_ID('nsn_view', 'V') IS NOT NULL
    DROP VIEW nsn_view;
GO

-- Create the view
CREATE VIEW nsn_view AS
SELECT 
    n.id,
    n.nsn_code,
    n.description,
    n.part_number,
    n.revision,
    n.notes,
    n.directory_url,
    (SELECT COUNT(*) FROM contracts_clin c WHERE c.nsn_id = n.id) AS clin_count,
    -- Create a concatenated search vector for faster text search
    CONCAT(
        ISNULL(n.nsn_code, ''), ' ',
        ISNULL(n.description, ''), ' ',
        ISNULL(n.part_number, ''), ' ',
        ISNULL(n.revision, '')
    ) AS search_vector
FROM 
    contracts_nsn n;
GO 