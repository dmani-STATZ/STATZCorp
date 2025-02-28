-- SQL Server script to migrate data from STATZ_SUB_CONTRACTS_TBL to Clin and ClinFinance tables
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
    SELECT DISTINCT CreatedBy FROM [ContractLog].[dbo].STATZ_SUB_CONTRACTS_TBL WHERE CreatedBy IS NOT NULL
    UNION
    SELECT DISTINCT ModifiedBy FROM [ContractLog].[dbo].STATZ_SUB_CONTRACTS_TBL WHERE ModifiedBy IS NOT NULL
);

-- Create a temporary table to store valid contract IDs
CREATE TABLE #ValidContracts (
    contract_id INT
);

-- Populate with contract IDs that exist in the contracts_contract table
INSERT INTO #ValidContracts (contract_id)
SELECT id FROM contracts_contract;

-- Create a temporary table to store valid supplier IDs
CREATE TABLE #ValidSuppliers (
    supplier_id INT
);

-- Populate with supplier IDs that exist in the contracts_supplier table
INSERT INTO #ValidSuppliers (supplier_id)
SELECT id FROM contracts_supplier;

-- Create a temporary table to store valid NSN IDs
CREATE TABLE #ValidNsns (
    nsn_id INT
);

-- Populate with NSN IDs that exist in the contracts_nsn table
INSERT INTO #ValidNsns (nsn_id)
SELECT id FROM contracts_nsn;

-- Create a temporary table to store valid ClinType IDs
CREATE TABLE #ValidClinTypes (
    clin_type_id INT
);

-- Populate with ClinType IDs that exist in the contracts_clintype table
INSERT INTO #ValidClinTypes (clin_type_id)
SELECT id FROM contracts_clintype;

-- Create a temporary table to store valid SpecialPaymentTerms IDs
CREATE TABLE #ValidSPTs (
    spt_id INT
);

-- Populate with SpecialPaymentTerms IDs that exist in the contracts_specialpaymentterms table
INSERT INTO #ValidSPTs (spt_id)
SELECT id FROM contracts_specialpaymentterms;

-- Enable identity insert for contracts_clinfinance
SET IDENTITY_INSERT [dbo].[contracts_clinfinance] ON;

-- Step 1: Migrate ClinFinance records first
-- We'll use the same IDs as the original table to maintain relationships
INSERT INTO contracts_clinfinance (
    id,
    special_payment_terms_id,
    special_payment_terms_paid,
    contract_value,
    po_amount,
    paid_amount,
    paid_date,
    wawf_payment,
    wawf_recieved,
    wawf_invoice,
    plan_gross,
    planned_split,
    created_by_id,
    created_on,
    modified_by_id,
    modified_on
)
SELECT 
    ID,
    -- Map SPT_Type to special_payment_terms_id, but only if it exists in the SpecialPaymentTerms table
    CASE 
        WHEN SPT = 1 AND EXISTS (SELECT 1 FROM #ValidSPTs WHERE spt_id = 
            (SELECT TOP 1 id FROM contracts_specialpaymentterms WHERE code = SPT_Type)) 
        THEN (SELECT TOP 1 id FROM contracts_specialpaymentterms WHERE code = SPT_Type)
        ELSE NULL 
    END,
    SPT_Paid,
    ContractDol,
    SubPODol,
    SubPaidDol,
    SubPaidDate,
    WAWFPaymentDol,
    DatePayRecv,
    WAWFInvoice,
    PlanGrossDol,
    PlanSplit_per_PPIbid,
    -- Map usernames to user IDs
    (SELECT user_id FROM #UserMapping WHERE username = CreatedBy),
    ISNULL(CreatedOn, GETDATE()),
    (SELECT user_id FROM #UserMapping WHERE username = ModifiedBy),
    ISNULL(ModifiedOn, GETDATE())
FROM [ContractLog].[dbo].STATZ_SUB_CONTRACTS_TBL;

-- Enable identity insert for contracts_clinfinance
SET IDENTITY_INSERT [dbo].[contracts_clinfinance] OFF;


-- Enable identity insert for contracts_clin
SET IDENTITY_INSERT [dbo].[contracts_clin] ON;
-- Step 2: Migrate Clin records
-- We'll use the same IDs as the original table
-- IMPORTANT: We're now filtering to only include records where Contract_ID exists in contracts_contract table
INSERT INTO contracts_clin (
    id,
    clin_finance_id,
    contract_id,
    sub_contract,
    po_num_ext,
    tab_num,
    clin_po_num,
    po_number,
    clin_type_id,
    supplier_id,
    nsn_id,
    ia,
    fob,
    order_qty,
    ship_qty,
    due_date,
    due_date_late,
    supplier_due_date,
    supplier_due_date_late,
    ship_date,
    ship_date_late,
    created_by_id,
    created_on,
    modified_by_id,
    modified_on
)
SELECT 
    ID,
    ID, -- Same ID for clin_finance since we're maintaining the relationship
    Contract_ID, -- Now we're only including records with valid contract_id values
    [Sub-Contract],
    PONumExt,
    TabNum,
    SubPONum,
    PONumber,
    -- Only include clin_type_id if it exists in the contracts_clintype table
    CASE WHEN EXISTS (SELECT 1 FROM #ValidClinTypes WHERE clin_type_id = Type_ID)
         THEN Type_ID
         ELSE NULL
    END,
    -- Only include supplier_id if it exists in the contracts_supplier table
    CASE WHEN EXISTS (SELECT 1 FROM #ValidSuppliers WHERE supplier_id = Vendor_ID)
         THEN Vendor_ID
         ELSE NULL
    END,
    -- Only include nsn_id if it exists in the contracts_nsn table
    CASE WHEN EXISTS (SELECT 1 FROM #ValidNsns WHERE nsn_id = NSN_ID)
         THEN NSN_ID
         ELSE NULL
    END,
    IA,
    FOB,
    OrderQty,
    ShipQty,
    SubDueDate, -- Using SubDueDate as the main due_date
    LateSDD, -- Using LateSDD as due_date_late
    VendorDueDate,
    LateShipQDD,
    ShipDate,
    LateShip,
    -- Map usernames to user IDs
    (SELECT user_id FROM #UserMapping WHERE username = CreatedBy),
    ISNULL(CreatedOn, GETDATE()),
    (SELECT user_id FROM #UserMapping WHERE username = ModifiedBy),
    ISNULL(ModifiedOn, GETDATE())
FROM [ContractLog].[dbo].STATZ_SUB_CONTRACTS_TBL
-- This WHERE clause is the key change - only include records with valid contract_id values
WHERE Contract_ID IS NOT NULL 
AND EXISTS (SELECT 1 FROM #ValidContracts WHERE contract_id = Contract_ID);

-- Enable identity insert for contracts_clin
SET IDENTITY_INSERT [dbo].[contracts_clin] OFF;

-- Print summary of missing foreign keys
SELECT 'Missing Contract IDs: ' + 
       CAST((SELECT COUNT(*) FROM [ContractLog].[dbo].STATZ_SUB_CONTRACTS_TBL 
             WHERE Contract_ID IS NOT NULL 
             AND NOT EXISTS (SELECT 1 FROM #ValidContracts WHERE contract_id = Contract_ID)) AS VARCHAR) AS MissingContracts;

SELECT 'Missing Supplier IDs: ' + 
       CAST((SELECT COUNT(*) FROM [ContractLog].[dbo].STATZ_SUB_CONTRACTS_TBL 
             WHERE Vendor_ID IS NOT NULL 
             AND NOT EXISTS (SELECT 1 FROM #ValidSuppliers WHERE supplier_id = Vendor_ID)) AS VARCHAR) AS MissingSuppliers;

SELECT 'Missing NSN IDs: ' + 
       CAST((SELECT COUNT(*) FROM [ContractLog].[dbo].STATZ_SUB_CONTRACTS_TBL 
             WHERE NSN_ID IS NOT NULL 
             AND NOT EXISTS (SELECT 1 FROM #ValidNsns WHERE nsn_id = NSN_ID)) AS VARCHAR) AS MissingNsns;

SELECT 'Missing ClinType IDs: ' + 
       CAST((SELECT COUNT(*) FROM [ContractLog].[dbo].STATZ_SUB_CONTRACTS_TBL 
             WHERE Type_ID IS NOT NULL 
             AND NOT EXISTS (SELECT 1 FROM #ValidClinTypes WHERE clin_type_id = Type_ID)) AS VARCHAR) AS MissingClinTypes;

-- Clean up
DROP TABLE #UserMapping;
DROP TABLE #ValidContracts;
DROP TABLE #ValidSuppliers;
DROP TABLE #ValidNsns;
DROP TABLE #ValidClinTypes;
DROP TABLE #ValidSPTs;

-- Print summary
SELECT 'Migration complete. ' + 
       CAST((SELECT COUNT(*) FROM contracts_clin) AS VARCHAR) + ' CLINs and ' +
       CAST((SELECT COUNT(*) FROM contracts_clinfinance) AS VARCHAR) + ' ClinFinance records migrated.' AS Result; 