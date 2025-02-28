-- SQL Server script to migrate data from STATZ_CONTRACTS_TBL to Contract table
-- Run this in SQL Server Management Studio

-- First, let's handle user mapping
-- Create a temporary table to map usernames to user IDs
CREATE TABLE #UserMapping (
    username NVARCHAR(20),
    user_id INT
);

-- Populate the user mapping table
-- You'll need to adjust this query based on your actual auth_user table structure
INSERT INTO #UserMapping (username, user_id)
SELECT username, id
FROM auth_user
WHERE username IN (
    SELECT DISTINCT CreatedBy FROM STATZ_CONTRACTS_TBL WHERE CreatedBy IS NOT NULL
    UNION
    SELECT DISTINCT ModifiedBy FROM STATZ_CONTRACTS_TBL WHERE ModifiedBy IS NOT NULL
    UNION
    SELECT DISTINCT ReviewedBy FROM STATZ_CONTRACTS_TBL WHERE ReviewedBy IS NOT NULL
);

-- Migrate Contract records
INSERT INTO contracts_contract (
    id,
    contract_number,
    open,
    date_closed,
    cancelled,
    date_canceled,
    canceled_reason_id,
    po_number,
    tab_num,
    buyer_id,
    contract_type_id,
    award_date,
    due_date,
    due_date_late,
    sales_class_id,
    survey_date,
    survey_type,
    assigned_user,
    assigned_date,
    nist,
    files_url,
    reviewed,
    reviewed_by,
    reviewed_on,
    created_by_id,
    created_on,
    modified_by_id,
    modified_on
)
SELECT 
    ID,
    ContractNum,
    ContractOpen,
    DateClosed,
    ContractCancelled,
    DateCancelled,
    ReasonCancelled,
    PONumber,
    TabNum,
    Buyer_ID,
    Type_ID,
    [Award Date],
    ContractDueDate,
    LateShipCDD,
    SalesClass,
    SurveyDate,
    SurveyType,
    AssignedUser,
    AssignedDate,
    NIST,
    URL,
    Reviewed,
    ReviewedBy,
    ReviewedOn,
    -- Map usernames to user IDs
    (SELECT user_id FROM #UserMapping WHERE username = CreatedBy),
    isnull(CreatedOn, getdate()),
    (SELECT user_id FROM #UserMapping WHERE username = ModifiedBy),
    isnull(ModifiedOn, getdate())
FROM STATZ_CONTRACTS_TBL;

-- Clean up
DROP TABLE #UserMapping;

-- Print summary
SELECT 'Migration complete. ' + CAST((SELECT COUNT(*) FROM contracts_contract) AS VARCHAR) + ' Contract records migrated.' AS Result; 