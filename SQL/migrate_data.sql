USE [STATZWeb_dev]
-- Rollback any open transactions to ensure a clean state
IF @@TRANCOUNT > 0
BEGIN
    -- -- print 'Rolling back open transactions before migration.';
    ROLLBACK TRANSACTION;
END

-- Proceed with migration
-- Delete all the records in the processing tables
DELETE FROM processing_processclin;
DELETE FROM processing_queueclin;
DELETE FROM processing_contractsplit;
DELETE FROM processing_processcontract;
DELETE FROM processing_queuecontract;

DBCC CHECKIDENT ('processing_processcontract', RESEED, 0);
DBCC CHECKIDENT ('processing_processclin', RESEED, 0);
DBCC CHECKIDENT ('processing_contractsplit', RESEED, 0);
DBCC CHECKIDENT ('processing_queuecontract', RESEED, 0);
DBCC CHECKIDENT ('processing_queueclin', RESEED, 0);


-- Delete all rows and reseed identity columns to 0
    -- Insert statements for procedure here
    print ('##########################################')
    print 'Deleting rows and reseeding identity columns to 0';
    print ('##########################################')
    DELETE FROM contracts_reminder
	DBCC CHECKIDENT ('contracts_reminder', RESEED, 0);
	DELETE FROM contracts_note;
	DBCC CHECKIDENT ('contracts_note', RESEED, 0);
	DELETE FROM contracts_idiqcontractdetails;
	DBCC CHECKIDENT ('contracts_idiqcontractdetails', RESEED, 0);
	DELETE FROM contracts_suppliercertification;
	DBCC CHECKIDENT ('contracts_suppliercertification', RESEED, 0);
	DELETE FROM contracts_supplierclassification;
	DBCC CHECKIDENT ('contracts_supplierclassification', RESEED, 0);
	DELETE FROM contracts_acknowledgementletter;
	DBCC CHECKIDENT ('contracts_acknowledgementletter', RESEED, 0);
	DELETE FROM contracts_clinacknowledgment;
	DBCC CHECKIDENT ('contracts_clinacknowledgment', RESEED, 0);
    DELETE FROM contracts_paymenthistory;
    DBCC CHECKIDENT ('contracts_paymenthistory', RESEED, 0);
    DELETE FROM contracts_contractsplit;
    DBCC CHECKIDENT ('contracts_contractsplit', RESEED, 0);


	-- Second Level
	DELETE FROM contracts_clin;
	DBCC CHECKIDENT ('contracts_clin', RESEED, 0);
    DELETE FROM contracts_foldertracking;
    DBCC CHECKIDENT ('contracts_foldertracking', RESEED, 0);
    DELETE FROM contracts_expedite;
    DBCC CHECKIDENT ('contracts_expedite', RESEED, 0);


	-- Third Level
	DELETE FROM contracts_contract;
	DBCC CHECKIDENT ('contracts_contract', RESEED, 0);
	DELETE FROM contracts_idiqcontract;
	DBCC CHECKIDENT ('contracts_idiqcontract', RESEED, 0);


	-- Fourth Level
	DELETE FROM contracts_supplier;
	DBCC CHECKIDENT ('contracts_supplier', RESEED, 0);
	DELETE FROM contracts_contact;
	DBCC CHECKIDENT ('contracts_contact', RESEED, 0);


	-- Base Level
    DELETE FROM contracts_contractstatus;
    DBCC CHECKIDENT ('contracts_contractstatus', RESEED, 0);
	DELETE FROM contracts_address;
	DBCC CHECKIDENT ('contracts_address', RESEED, 0);
	DELETE FROM contracts_suppliertype;
	DBCC CHECKIDENT ('contracts_suppliertype', RESEED, 0);
	DELETE FROM contracts_clintype;
	DBCC CHECKIDENT ('contracts_clintype', RESEED, 0);
	DELETE FROM contracts_contracttype;
	DBCC CHECKIDENT ('contracts_contracttype', RESEED, 0);
	DELETE FROM contracts_canceledreason;
	DBCC CHECKIDENT ('contracts_canceledreason', RESEED, 0);
	DELETE FROM contracts_salesclass;
	DBCC CHECKIDENT ('contracts_salesclass', RESEED, 0);
	DELETE FROM contracts_buyer;
	DBCC CHECKIDENT ('contracts_buyer', RESEED, 0);
	DELETE FROM contracts_nsn;
	DBCC CHECKIDENT ('contracts_nsn', RESEED, 0);
	DELETE FROM contracts_specialpaymentterms;
	DBCC CHECKIDENT ('contracts_specialpaymentterms', RESEED, 0);
	DELETE FROM contracts_certificationtype;
	DBCC CHECKIDENT ('contracts_certificationtype', RESEED, 0);
	DELETE FROM contracts_classificationtype;
	DBCC CHECKIDENT ('contracts_classificationtype', RESEED, 0);


    -- InventoryItem migration
    DELETE FROM STATZ_WAREHOUSE_INVENTORY_TBL;
    DBCC CHECKIDENT ('STATZ_WAREHOUSE_INVENTORY_TBL', RESEED, 0);


    -- AccessLog
    DELETE FROM accesslog_visitor;
    DBCC CHECKIDENT ('accesslog_visitor', RESEED, 0);
    DELETE FROM accesslog_staged;
    DBCC CHECKIDENT ('accesslog_staged', RESEED, 0);


-- Migration Script for STATZWeb Data
-- This script migrates data from ContractLog and CommonCore to the new Django models
-- while preserving IDs and relationships

    print ('##########################################')
    print 'Creating User Mapping Table';
    print ('##########################################')

-- Create and populate user mapping table
IF OBJECT_ID('tempdb..#UserMapping') IS NOT NULL
    DROP TABLE #UserMapping;

CREATE TABLE #UserMapping (
    user_id INT,
    username NVARCHAR(150)
);

INSERT INTO #UserMapping (user_id, username)
SELECT        DISTINCT auth_user.id, tbl.ModifiedBy
FROM            auth_user INNER JOIN
                         ContractLog.dbo.STATZ_SUB_CONTRACTS_TBL as tbl ON auth_user.username = lower(tbl.ModifiedBy)
UNION
SELECT        DISTINCT auth_user.id, tbl.CreatedBy
FROM            auth_user INNER JOIN
                         ContractLog.dbo.STATZ_SUB_CONTRACTS_TBL as tbl ON auth_user.username = lower(tbl.CreatedBy)
UNION
SELECT        DISTINCT auth_user.id, tbl.CreatedBy
FROM            auth_user INNER JOIN
                         ContractLog.dbo.STATZ_CONTRACTS_TBL as tbl ON auth_user.username = lower(tbl.CreatedBy)
UNION
SELECT        DISTINCT auth_user.id, tbl.ModifiedBy
FROM            auth_user INNER JOIN
                         ContractLog.dbo.STATZ_CONTRACTS_TBL as tbl ON auth_user.username = lower(tbl.ModifiedBy)
UNION
SELECT        DISTINCT auth_user.id, tbl.CreatedBy
FROM            auth_user INNER JOIN
                         ContractLog.dbo.STATZ_NOTES_TBL as tbl ON auth_user.username = lower(tbl.CreatedBy)
UNION
SELECT        DISTINCT auth_user.id, tbl.ModifiedBy
FROM            auth_user INNER JOIN
                         ContractLog.dbo.STATZ_NOTES_TBL as tbl ON auth_user.username = lower(tbl.ModifiedBy)
UNION
SELECT        DISTINCT auth_user.id, tbl.CreatedBy
FROM            auth_user INNER JOIN
                         [CommonCore].dbo.STATZ_SUPPLIERS_TBL as tbl ON auth_user.username = lower(tbl.CreatedBy)
UNION
SELECT        DISTINCT auth_user.id, tbl.ModifiedBy
FROM            auth_user INNER JOIN
                         [CommonCore].dbo.STATZ_SUPPLIERS_TBL as tbl ON auth_user.username = lower(tbl.ModifiedBy)
UNION
SELECT        DISTINCT auth_user.id, tbl.CreatedBy
FROM            auth_user INNER JOIN
                         [CommonCore].dbo.STATZ_NSN_CODE_TBL as tbl ON auth_user.username = lower(tbl.CreatedBy)
UNION
SELECT        DISTINCT auth_user.id, tbl.ModifiedBy
FROM            auth_user INNER JOIN
                         [CommonCore].dbo.STATZ_NSN_CODE_TBL as tbl ON auth_user.username = lower(tbl.ModifiedBy)


-- Create indexes for better performance
CREATE INDEX IX_UserMapping_Username ON #UserMapping(username);
CREATE INDEX IX_UserMapping_UserId ON #UserMapping(user_id);

-- -- -- print unmapped users for review
SELECT 'Unmapped Users:' AS Category, username 
FROM #UserMapping 
WHERE user_id IS NULL;

GO

print ('##########################################')
print 'Creating EnsureIdentityInsertOff Procedure';
print ('##########################################')

-- Helper procedure to ensure IDENTITY_INSERT is OFF
IF OBJECT_ID('tempdb..#EnsureIdentityInsertOff') IS NOT NULL
    DROP PROCEDURE #EnsureIdentityInsertOff;
GO

CREATE PROCEDURE #EnsureIdentityInsertOff
AS
BEGIN
    DECLARE @TableName NVARCHAR(128);
    DECLARE @SQL NVARCHAR(MAX);

    -- Cursor to iterate over tables with identity columns, excluding views
    DECLARE IdentityCursor CURSOR FOR
    SELECT TABLE_NAME
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE COLUMNPROPERTY(OBJECT_ID(TABLE_SCHEMA + '.' + TABLE_NAME), COLUMN_NAME, 'IsIdentity') = 1
    AND TABLE_NAME IN (SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE');

    OPEN IdentityCursor;
    FETCH NEXT FROM IdentityCursor INTO @TableName;

    WHILE @@FETCH_STATUS = 0
    BEGIN
        -- Check if IDENTITY_INSERT is ON for the table
        SET @SQL = 'IF EXISTS (SELECT 1 FROM sys.identity_columns WHERE OBJECT_NAME(object_id) = ''' + @TableName + ''' AND is_identity = 1)
                    BEGIN
                        SET IDENTITY_INSERT ' + @TableName + ' OFF;
                    END';
        EXEC sp_executesql @SQL;

        FETCH NEXT FROM IdentityCursor INTO @TableName;
    END

    CLOSE IdentityCursor;
    DEALLOCATE IdentityCursor;
END;
GO

-- Before each migration, call the procedure
EXEC #EnsureIdentityInsertOff;

-- Address migration from Suppliers
-- -- print 'Migrating supplier addresses'

print ('##########################################')
print 'Migrating supplier addresses'
print ('##########################################')

BEGIN TRY
    DECLARE @RowCount INT;
    DECLARE @ErrorMessage NVARCHAR(MAX);
    
    BEGIN TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF before setting it ON
    SET IDENTITY_INSERT [dbo].[contracts_address] ON;
    
    -- Insert addresses from suppliers
    INSERT INTO [dbo].[contracts_address] (id, address_line_1, address_line_2, city, state, zip)
    SELECT 
        ROW_NUMBER() OVER (ORDER BY ID) + 10000 AS id, -- Start at 10001 to avoid conflicts
        [Street Address] AS address_line_1,
        NULL AS address_line_2,
        City AS city,
        State AS state,
        ZIP AS zip
    FROM CommonCore.dbo.STATZ_SUPPLIERS_TBL
    WHERE [Street Address] IS NOT NULL;
    
    -- Track supplier addresses
    IF OBJECT_ID('tempdb..#AddressMapping') IS NULL
    BEGIN
        CREATE TABLE #AddressMapping (
            address_id INT,
            source_table NVARCHAR(100),
            source_id INT,
            address_type NVARCHAR(50)
        );
    END
    
    INSERT INTO #AddressMapping (address_id, source_table, source_id, address_type)
    SELECT 
        ROW_NUMBER() OVER (ORDER BY ID) + 10000,
        'STATZ_SUPPLIERS_TBL',
        ID,
        'physical'
    FROM CommonCore.dbo.STATZ_SUPPLIERS_TBL
    WHERE [Street Address] IS NOT NULL;
    
    SET @RowCount = @@ROWCOUNT;
    
    SET IDENTITY_INSERT [dbo].[contracts_address] OFF;
    
    COMMIT TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF after operation
    
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;
    
    SET @ErrorMessage = ERROR_MESSAGE();
    -- -- print 'Error migrating supplier addresses: ' + @ErrorMessage;
END CATCH;
GO

-- Address migration from Contacts
print ('##########################################')
print 'Migrating contact addresses'
print ('##########################################')

BEGIN TRY
    DECLARE @RowCount INT;
    DECLARE @ErrorMessage NVARCHAR(MAX);
    
    BEGIN TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF before setting it ON
    SET IDENTITY_INSERT [dbo].[contracts_address] ON;
    
    -- Insert addresses from contacts
    INSERT INTO contracts_address (id, address_line_1, address_line_2, city, state, zip)
    SELECT 
        ROW_NUMBER() OVER (ORDER BY ID) + 20000 AS id, -- Start at 20001 to avoid conflicts with supplier addresses
        Address AS address_line_1,
        Address2 AS address_line_2,
        City AS city,
        State AS state,
        ZIP AS zip
    FROM CommonCore.dbo.STATZ_SALES_CONTACTS_TBL
    WHERE Address IS NOT NULL;
    
    -- Track contact addresses
    IF OBJECT_ID('tempdb..#AddressMapping') IS NULL
    BEGIN
        CREATE TABLE #AddressMapping (
            address_id INT,
            source_table NVARCHAR(100),
            source_id INT,
            address_type NVARCHAR(50)
        );
    END
    
    INSERT INTO #AddressMapping (address_id, source_table, source_id, address_type)
    SELECT 
        ROW_NUMBER() OVER (ORDER BY ID) + 20000,
        'STATZ_SALES_CONTACTS_TBL',
        ID,
        'contact'
    FROM CommonCore.dbo.STATZ_SALES_CONTACTS_TBL
    WHERE Address IS NOT NULL;
    
    SET @RowCount = @@ROWCOUNT;
    
    SET IDENTITY_INSERT [dbo].[contracts_address] OFF;
    
    COMMIT TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF after operation
    
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;
    
    SET @ErrorMessage = ERROR_MESSAGE();
    -- -- print 'Error migrating contact addresses: ' + @ErrorMessage;
END CATCH;
GO

-- Contact migration (updated to use address mapping)
print ('##########################################')
print 'Migrating contacts'
print ('##########################################')

BEGIN TRY
    DECLARE @RowCount INT;
    DECLARE @ErrorMessage NVARCHAR(MAX);
    
    BEGIN TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF before setting it ON
    SET IDENTITY_INSERT [dbo].[contracts_contact] ON;
    
    INSERT INTO contracts_contact (id, salutation, name, company, title, phone, email, address_id, notes)
    SELECT 
        sc.ID AS id,
        ISNULL(sc.Title, '') AS salutation,  -- Use empty string if NULL
        sc.FirstName + ' ' + ISNULL(sc.LastName, '') AS name,
        sc.Company AS company,
        sc.JobTitle AS title,
        sc.BusinessPhone AS phone,
        sc.EmailAddress AS email,
        am.address_id,  -- Use mapped address ID
        sc.Notes AS notes
    FROM CommonCore.dbo.STATZ_SALES_CONTACTS_TBL sc
    LEFT JOIN #AddressMapping am ON am.source_table = 'STATZ_SALES_CONTACTS_TBL' 
        AND am.source_id = sc.ID 
        AND am.address_type = 'contact';
    
    SET @RowCount = @@ROWCOUNT;
    
    SET IDENTITY_INSERT [dbo].[contracts_contact] OFF;
    
    COMMIT TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF after operation
    
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;
    
    SET @ErrorMessage = ERROR_MESSAGE();
    -- -- print 'Error migrating contacts: ' + @ErrorMessage;
END CATCH;
GO

EXEC #EnsureIdentityInsertOff;

-- NSN migration
print ('##########################################')
print 'NSN migration'
print ('##########################################')

BEGIN TRY
    DECLARE @RowCount INT;
    DECLARE @ErrorMessage NVARCHAR(MAX);
    
    BEGIN TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF before setting it ON
    SET IDENTITY_INSERT [dbo].[contracts_nsn] ON;
    
    INSERT INTO contracts_nsn (id, nsn_code, description, part_number, revision, notes, directory_url, created_on, modified_on, created_by_id, modified_by_id)
    SELECT 
        ID AS id,
        NSN AS nsn_code,
        [Item Description] AS description,
        NULL AS part_number,
        NULL AS revision,
        Note AS notes,
        Directory AS directory_url,
        ISNULL(CreatedOn, SYSDATETIME()) AS created_on,  -- Set to current datetime if null
        ISNULL(ModifiedOn, SYSDATETIME()) AS modified_on,  -- Set to current datetime if null
        ISNULL(um_created.user_id, 1) AS created_by_id,  -- Map using UserMapping
        ISNULL(um_modified.user_id, 1) AS modified_by_id  -- Map using UserMapping
    FROM CommonCore.dbo.STATZ_NSN_CODE_TBL
    LEFT JOIN #UserMapping um_created ON CreatedBy = um_created.username
    LEFT JOIN #UserMapping um_modified ON ModifiedBy = um_modified.username;
    
    SET @RowCount = @@ROWCOUNT;
    
    SET IDENTITY_INSERT [dbo].[contracts_nsn] OFF;
    
    COMMIT TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF after operation
    
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;
    
    SET @ErrorMessage = ERROR_MESSAGE();
    -- -- print 'Error migrating NSNs: ' + @ErrorMessage;
END CATCH;
GO


-- Supplier type migration
print ('##########################################')
print 'Supplier type migration'
print ('##########################################')

INSERT INTO [dbo].[contracts_suppliertype]
           ([code],[description])
SELECT [Code]
      ,[Description]
FROM [CommonCore].[dbo].[STATZ_SUPPLIER_TYPE_CODE_TBL]


-- Special payment terms migration
print ('##########################################')
print 'Special payment terms migration'
print ('##########################################')

INSERT INTO [dbo].[contracts_specialpaymentterms]
           ([code],[terms])
SELECT [Code]
      ,[Description]
FROM [CommonCore].[dbo].[STATZ_SPT_CODE_TBL]



-- Supplier migration: Insert with packhouse_id as NULL
print ('##########################################')
print 'Supplier migration: Insert with packhouse_id as NULL'
print ('##########################################')

BEGIN TRY
    DECLARE @RowCount INT;
    DECLARE @ErrorMessage NVARCHAR(MAX);
    
    BEGIN TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF before setting it ON
    SET IDENTITY_INSERT [dbo].[contracts_supplier] ON;
    
    INSERT INTO contracts_supplier (
        id, name, cage_code, supplier_type_id, billing_address_id, shipping_address_id,
        physical_address_id, business_phone, business_fax, business_email, contact_id,
        probation, probation_on, probation_by_id, conditional, conditional_on,
        conditional_by_id, special_terms_id, special_terms_on, prime, ppi, iso,
        notes, is_packhouse, packhouse_id, files_url, allows_gsi, created_on, modified_on,
        created_by_id, modified_by_id
    )
    SELECT 
        s.ID AS id,
        s.[Sub-Contractor] AS name,
        s.CageCode AS cage_code,
        st.id AS supplier_type_id,
        am.address_id AS billing_address_id,  -- Use mapped address for billing
        am.address_id AS shipping_address_id, -- Use mapped address for shipping
        am.address_id AS physical_address_id, -- Use mapped address for physical
        s.Phone AS business_phone,
        NULL AS business_fax,
        s.Email AS business_email,
        c.id AS contact_id,
        s.Probation AS probation,
        s.ProbationOn AS probation_on,
        ISNULL(um_probation.user_id, 1) AS probation_by_id,  -- Map using UserMapping
        s.Conditional AS conditional,
        s.ConditionalOn AS conditional_on,
        ISNULL(um_conditional.user_id, 1) AS conditional_by_id,  -- Map using UserMapping
        spt.id AS special_terms_id,
        NULL AS special_terms_on,
        s.Prime AS prime,
        s.PPI AS ppi,
        s.ISO AS iso,
        s.Notes AS notes,
        s.isPackhouse AS is_packhouse,
        NULL AS packhouse_id,  -- Initially set to NULL
        s.DirPath AS files_url,
        s.AllowsGSI AS allows_gsi,
        ISNULL(s.CreatedOn, SYSDATETIME()) AS created_on,  -- Set to current datetime if null
        ISNULL(s.ModifiedOn, SYSDATETIME()) AS modified_on,  -- Set to current datetime if null
        ISNULL(um_created.user_id, 1) AS created_by_id,
        ISNULL(um_modified.user_id, 1) AS modified_by_id
    FROM CommonCore.dbo.STATZ_SUPPLIERS_TBL s
    LEFT JOIN contracts_suppliertype st ON s.Type = st.description
    LEFT JOIN #AddressMapping am ON am.source_table = 'STATZ_SUPPLIERS_TBL' 
        AND am.source_id = s.ID 
        AND am.address_type = 'physical'
    LEFT JOIN contracts_contact c ON s.PrimaryContactID = c.id
    LEFT JOIN contracts_specialpaymentterms spt ON s.SPT = spt.code
    LEFT JOIN #UserMapping um_created ON s.CreatedBy = um_created.username
    LEFT JOIN #UserMapping um_modified ON s.ModifiedBy = um_modified.username
    LEFT JOIN #UserMapping um_probation ON s.ProbationBy = um_probation.username
    LEFT JOIN #UserMapping um_conditional ON s.ConditionalBy = um_conditional.username;
    
    SET @RowCount = @@ROWCOUNT;


    insert into contracts_supplier (id, name, cage_code, created_on, modified_on, created_by_id, modified_by_id)
    values (0,'UNKNOWN','00000',SYSDATETIME(),SYSDATETIME(),1,1)

    
    SET IDENTITY_INSERT [dbo].[contracts_supplier] OFF;
    
    COMMIT TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF after operation
    
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;
    
    SET @ErrorMessage = ERROR_MESSAGE();
    -- -- print 'Error migrating suppliers: ' + @ErrorMessage;
END CATCH;
GO

-- Supplier Certifications types migration
print ('##########################################')
print 'Supplier Certifications types migration'
print ('##########################################')

INSERT INTO [dbo].[contracts_certificationtype]
           ([name]
           ,[code])
SELECT [Code]
      ,[Code]
FROM [CommonCore].[dbo].[STATZ_QMS_CODE_TBL];


-- Supplier Certifications migration
print ('##########################################')
print 'Supplier Certifications migration'
print ('##########################################')

INSERT INTO [dbo].[contracts_suppliercertification]
           ([certification_date]
           ,[certification_expiration]
           ,[certification_type_id]
           ,[supplier_id]
           ,[compliance_status])
SELECT        qms.CreatedOn, qms.ExpDate, contracts_certificationtype.id AS Expr1, qms.Supplier_ID, qms.Compliance
FROM            CommonCore.dbo.STATZ_QMS_TBL as qms INNER JOIN
                         contracts_certificationtype ON qms.Type = contracts_certificationtype.name INNER JOIN
                         contracts_supplier ON qms.Supplier_ID = contracts_supplier.id



-- Supplier Classification type migration
print ('##########################################')
print 'Supplier Classification type migration'
print ('##########################################')

set identity_insert [dbo].[contracts_classificationtype] ON;

INSERT INTO [dbo].[contracts_classificationtype] ([id],[name]) VALUES (1,'Small Business (SB)');
INSERT INTO [dbo].[contracts_classificationtype] ([id],[name]) VALUES (2,'Service Disabled (SD)');
INSERT INTO [dbo].[contracts_classificationtype] ([id],[name]) VALUES (3,'Women Owned (WOSB)');
INSERT INTO [dbo].[contracts_classificationtype] ([id],[name]) VALUES (4,'Veteran Owned (VOSB)');
INSERT INTO [dbo].[contracts_classificationtype] ([id],[name]) VALUES (5,'HUBZone (HZ)');
INSERT INTO [dbo].[contracts_classificationtype] ([id],[name]) VALUES (6,'8(a) Business Development (8a)');
INSERT INTO [dbo].[contracts_classificationtype] ([id],[name]) VALUES (7,'Community Development Corp (CDC)');
INSERT INTO [dbo].[contracts_classificationtype] ([id],[name]) VALUES (8,'Economically Disadvantaged (ED)');
INSERT INTO [dbo].[contracts_classificationtype] ([id],[name]) VALUES (9,'Minority Owned (MO)');
INSERT INTO [dbo].[contracts_classificationtype] ([id],[name]) VALUES (10,'Shutting Down');
INSERT INTO [dbo].[contracts_classificationtype] ([id],[name]) VALUES (11,'Native American Owned (NAO)');

set identity_insert [dbo].[contracts_classificationtype] OFF;


-- Supplier Classification migration
print ('##########################################')
print 'Supplier Classification migration'
print ('##########################################')
INSERT INTO [dbo].[contracts_supplierclassification] ([classification_date] ,[classification_type_id] ,[supplier_id])
SELECT sysdatetime(),1,sc.SupplierID FROM CommonCore.dbo.STATZ_SUPPLIER_CLASSIFICATION_TBL AS sc INNER JOIN
                         CommonCore.dbo.STATZ_SUPPLIERS_TBL AS s_1 ON sc.SupplierID = s_1.ID
WHERE        (sc.[Small Business] = 1);

INSERT INTO [dbo].[contracts_supplierclassification] ([classification_date] ,[classification_type_id] ,[supplier_id])
SELECT sysdatetime(),2,[SupplierID] FROM CommonCore.dbo.STATZ_SUPPLIER_CLASSIFICATION_TBL AS sc INNER JOIN
                         CommonCore.dbo.STATZ_SUPPLIERS_TBL AS s_1 ON sc.SupplierID = s_1.ID
WHERE sc.[Service Disabled]=1;

INSERT INTO [dbo].[contracts_supplierclassification] ([classification_date] ,[classification_type_id] ,[supplier_id])
SELECT sysdatetime(),3,[SupplierID] FROM CommonCore.dbo.STATZ_SUPPLIER_CLASSIFICATION_TBL AS sc INNER JOIN
                         CommonCore.dbo.STATZ_SUPPLIERS_TBL AS s_1 ON sc.SupplierID = s_1.ID
WHERE sc.[Women Owned]=1;

INSERT INTO [dbo].[contracts_supplierclassification] ([classification_date] ,[classification_type_id] ,[supplier_id])
SELECT sysdatetime(),4,[SupplierID] FROM CommonCore.dbo.STATZ_SUPPLIER_CLASSIFICATION_TBL AS sc INNER JOIN
                         CommonCore.dbo.STATZ_SUPPLIERS_TBL AS s_1 ON sc.SupplierID = s_1.ID
WHERE sc.[Veteran Owned]=1;

INSERT INTO [dbo].[contracts_supplierclassification] ([classification_date] ,[classification_type_id] ,[supplier_id])
SELECT sysdatetime(),5,[SupplierID] FROM CommonCore.dbo.STATZ_SUPPLIER_CLASSIFICATION_TBL AS sc INNER JOIN
                         CommonCore.dbo.STATZ_SUPPLIERS_TBL AS s_1 ON sc.SupplierID = s_1.ID
WHERE sc.[HUBZone]=1;

INSERT INTO [dbo].[contracts_supplierclassification] ([classification_date] ,[classification_type_id] ,[supplier_id])
SELECT sysdatetime(),6,[SupplierID] FROM CommonCore.dbo.STATZ_SUPPLIER_CLASSIFICATION_TBL AS sc INNER JOIN
                         CommonCore.dbo.STATZ_SUPPLIERS_TBL AS s_1 ON sc.SupplierID = s_1.ID
WHERE sc.[8A]=1;

INSERT INTO [dbo].[contracts_supplierclassification] ([classification_date] ,[classification_type_id] ,[supplier_id])
SELECT sysdatetime(),7,[SupplierID] FROM CommonCore.dbo.STATZ_SUPPLIER_CLASSIFICATION_TBL AS sc INNER JOIN
                         CommonCore.dbo.STATZ_SUPPLIERS_TBL AS s_1 ON sc.SupplierID = s_1.ID
WHERE sc.[Community Development Corp]=1;

INSERT INTO [dbo].[contracts_supplierclassification] ([classification_date] ,[classification_type_id] ,[supplier_id])
SELECT sysdatetime(),8,[SupplierID] FROM CommonCore.dbo.STATZ_SUPPLIER_CLASSIFICATION_TBL AS sc INNER JOIN
                         CommonCore.dbo.STATZ_SUPPLIERS_TBL AS s_1 ON sc.SupplierID = s_1.ID
WHERE sc.[Economically Disadvantaged]=1;

INSERT INTO [dbo].[contracts_supplierclassification] ([classification_date] ,[classification_type_id] ,[supplier_id])
SELECT sysdatetime(),9,[SupplierID] FROM CommonCore.dbo.STATZ_SUPPLIER_CLASSIFICATION_TBL AS sc INNER JOIN
                         CommonCore.dbo.STATZ_SUPPLIERS_TBL AS s_1 ON sc.SupplierID = s_1.ID
WHERE sc.[Minority Owned]=1;

INSERT INTO [dbo].[contracts_supplierclassification] ([classification_date] ,[classification_type_id] ,[supplier_id])
SELECT sysdatetime(),10,[SupplierID] FROM CommonCore.dbo.STATZ_SUPPLIER_CLASSIFICATION_TBL AS sc INNER JOIN
                         CommonCore.dbo.STATZ_SUPPLIERS_TBL AS s_1 ON sc.SupplierID = s_1.ID
WHERE sc.[Shutting Down]=1;

INSERT INTO [dbo].[contracts_supplierclassification] ([classification_date] ,[classification_type_id] ,[supplier_id])
SELECT sysdatetime(),11,[SupplierID] FROM CommonCore.dbo.STATZ_SUPPLIER_CLASSIFICATION_TBL AS sc INNER JOIN
                         CommonCore.dbo.STATZ_SUPPLIERS_TBL AS s_1 ON sc.SupplierID = s_1.ID
WHERE sc.[Native American Owned]=1;


-- canceledreason migration
print ('##########################################')
print 'Canceled reason migration'
print ('##########################################')

BEGIN TRY
    BEGIN TRANSACTION;

    SET IDENTITY_INSERT [dbo].[contracts_canceledreason] ON;

    INSERT INTO contracts_canceledreason (id, description)
    SELECT 
        ID,
        Reason
    FROM CommonCore.dbo.STATZ_CANCEL_CODE_TBL;

    SET IDENTITY_INSERT [dbo].[contracts_canceledreason] OFF;
    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;
    -- print 'Error migrating canceled reasons: ' + ERROR_MESSAGE();
END CATCH;
GO

-- Buyer migration
print ('##########################################')
print 'Buyer migration'
print ('##########################################')

BEGIN TRY
    BEGIN TRANSACTION;

    SET IDENTITY_INSERT [dbo].[contracts_buyer] ON;

    INSERT INTO contracts_buyer (id, description)
    SELECT 
        ID,
        Buyer
    FROM CommonCore.dbo.STATZ_BUYER_CODE_TBL;

    SET IDENTITY_INSERT [dbo].[contracts_buyer] OFF;
    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;
    -- print 'Error migrating buyers: ' + ERROR_MESSAGE();
END CATCH;
GO

-- contract type migration
print ('##########################################')
print 'Contract type migration'
print ('##########################################')

BEGIN TRY
    BEGIN TRANSACTION;

    SET IDENTITY_INSERT [dbo].[contracts_contracttype] ON;

    INSERT INTO contracts_contracttype (id, description)
    SELECT DISTINCT Type.ID, Type.Type
    FROM            CommonCore.dbo.STATZ_TYPE_CODE_TBL AS Type INNER JOIN
                            ContractLog.dbo.STATZ_CONTRACTS_TBL AS Contract ON Type.ID = Contract.Type_ID

    SET IDENTITY_INSERT [dbo].[contracts_contracttype] OFF;
    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;
    -- print 'Error migrating contract types: ' + ERROR_MESSAGE();
END CATCH;
GO

    -- sales class migration
print ('##########################################')
print 'Sales class migration'
print ('##########################################')

BEGIN TRY
    BEGIN TRANSACTION;

    SET IDENTITY_INSERT [dbo].[contracts_salesclass] ON;

    INSERT INTO contracts_salesclass (id, sales_team)
    SELECT        ID, SalesTeam
    FROM            [CommonCore].[dbo].[STATZ_SALES_CLASS_CODE_TBL]

    SET IDENTITY_INSERT [dbo].[contracts_salesclass] OFF;
    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;
    -- print 'Error migrating sales classes: ' + ERROR_MESSAGE();
END CATCH;
GO



-- Contract migration
print ('##########################################')
print 'Contract migration'
print ('##########################################')

BEGIN TRY
    DECLARE @RowCount INT;
    DECLARE @ErrorMessage NVARCHAR(MAX);
    
    BEGIN TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF before setting it ON
    SET IDENTITY_INSERT [dbo].[contracts_contract] ON;
    
    INSERT INTO contracts_contract (
        id, contract_number, status_id, [open], date_closed, cancelled,
        date_canceled, canceled_reason_id, po_number, tab_num, buyer_id,
        contract_type_id, award_date, due_date, due_date_late, sales_class_id,
        survey_date, survey_type, assigned_user_id, assigned_date, nist,
        files_url, reviewed, reviewed_by_id, reviewed_on, created_by_id,
        created_on, modified_by_id, modified_on
    )
    SELECT 
        c.ID,
        c.ContractNum,
        NULL, -- status_id will be derived
        c.ContractOpen,
        c.DateClosed,
        c.ContractCancelled,
        c.DateCancelled,
        NULLIF(c.ReasonCancelled, 0) AS canceled_reason_id,
        c.PONumber,
        c.TabNum,
        c.Buyer_ID,
        ct.id as contract_type_id,
        c.[Award Date],
        c.ContractDueDate,
        c.LateShipCDD,
        c.SalesClass,
        c.SurveyDate,
        c.SurveyType,
        ISNULL(um_assigned.user_id, 1) AS assigned_user_id,
        c.AssignedDate,
        c.NIST,
        c.URL,
        c.Reviewed,
        ISNULL(um_reviewed.user_id, 1) AS reviewed_by_id,
        c.ReviewedOn,
        ISNULL(um_created.user_id, 1) AS created_by_id,
        ISNULL(c.CreatedOn, SYSDATETIME()) AS created_on,
        ISNULL(um_modified.user_id, 1) AS modified_by_id,
        ISNULL(c.ModifiedOn, SYSDATETIME()) AS modified_on
    FROM ContractLog.dbo.STATZ_CONTRACTS_TBL c
    LEFT JOIN CommonCore.dbo.STATZ_TYPE_CODE_TBL ct ON c.Type_ID = ct.ID
    LEFT JOIN #UserMapping um_assigned ON c.AssignedUser = um_assigned.username
    LEFT JOIN #UserMapping um_reviewed ON c.ReviewedBy = um_reviewed.username
    LEFT JOIN #UserMapping um_created ON c.CreatedBy = um_created.username
    LEFT JOIN #UserMapping um_modified ON c.ModifiedBy = um_modified.username;
    
    SET @RowCount = @@ROWCOUNT;
    
    SET IDENTITY_INSERT [dbo].[contracts_contract] OFF;
    
    COMMIT TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF after operation
    
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;
    
    SET @ErrorMessage = ERROR_MESSAGE();
    -- print 'Error migrating contracts: ' + @ErrorMessage;
END CATCH;
GO

-- CLIN type migration
print ('##########################################')
print 'CLIN type migration'
print ('##########################################')

BEGIN TRY
    BEGIN TRANSACTION;

    SET IDENTITY_INSERT [dbo].[contracts_clintype] ON;

    INSERT INTO contracts_clintype (id, description)
    SELECT DISTINCT Type.ID, Type.Type
    FROM            CommonCore.dbo.STATZ_TYPE_CODE_TBL AS Type INNER JOIN
                            ContractLog.dbo.STATZ_SUB_CONTRACTS_TBL AS Contract ON Type.ID = Contract.Type_ID

    SET IDENTITY_INSERT [dbo].[contracts_clintype] OFF;
    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;
    -- print 'Error migrating CLIN types: ' + ERROR_MESSAGE();
END CATCH;
GO


-- CLIN migration
print ('##########################################')
print 'CLIN migration'
print ('##########################################')

BEGIN TRY
    DECLARE @RowCount INT;
    DECLARE @ErrorMessage NVARCHAR(MAX);
    
    BEGIN TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF before setting it ON
    SET IDENTITY_INSERT [dbo].[contracts_clin] ON;
    
    INSERT INTO contracts_clin (
        id,
        contract_id,
        item_number,
        item_type,
        item_value,
        unit_price,
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
        special_payment_terms_id,
        special_payment_terms_paid,
        price_per_unit,
        quote_value,
        paid_amount,
        paid_date,
        wawf_payment,
        wawf_recieved,
        wawf_invoice,
        created_by_id,
        created_on,
        modified_by_id,
        modified_on
    )
    SELECT 
        sc.ID,
        sc.Contract_ID,
        sc.[Sub-Contract], -- item_number maps to Sub-Contract
        sc.Type_ID,
        sc.ContractDol, -- item_value maps to SubPODol
        sc.PPP_Cont, -- unit_price maps to PPP_Cont
        sc.PONumExt,
        sc.TabNum,
        sc.SubPONum,
        sc.PONumber,
        sc.Type_ID,
        sc.Vendor_ID,
        sc.NSN_ID,
        sc.IA,
        sc.FOB,
        sc.OrderQty,
        sc.ShipQty,
        sc.SubDueDate,
        sc.LateSDD,
        sc.VendorDueDate,
        sc.LateShipQDD,
        sc.ShipDate,
        sc.LateShip,
        CASE WHEN sc.SPT = 1 THEN (SELECT id FROM contracts_specialpaymentterms WHERE code = sc.SPT_Type) ELSE NULL END,
        sc.SPT_Paid,
        sc.PPP_Sup,
        sc.SubPODol,
        sc.SubPaidDol,
        sc.SubPaidDate,
        sc.WAWFPaymentDol,
        sc.DatePayRecv,
        sc.WAWFInvoice,
        ISNULL(um_created.user_id, 1) AS created_by_id,
        ISNULL(sc.CreatedOn, SYSDATETIME()) AS created_on,
        ISNULL(um_modified.user_id, 1) AS modified_by_id,
        ISNULL(sc.ModifiedOn, SYSDATETIME()) AS modified_on
    FROM ContractLog.dbo.STATZ_SUB_CONTRACTS_TBL sc
    LEFT JOIN #UserMapping um_created ON sc.CreatedBy = um_created.username
    LEFT JOIN #UserMapping um_modified ON sc.ModifiedBy = um_modified.username;

    SET @RowCount = @@ROWCOUNT;
    
    SET IDENTITY_INSERT [dbo].[contracts_clin] OFF;
    
    COMMIT TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF after operation
    
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;
    
    SET @ErrorMessage = ERROR_MESSAGE();
    -- print 'Error migrating CLINs: ' + @ErrorMessage;
END CATCH;
GO


-- Update CLIN ITEM Type
UPDATE [dbo].[contracts_clin]
SET [item_type] = CASE
    WHEN [item_type] IN (1, 2, 15, 24, 29) THEN 'P'
    WHEN [item_type] = 17 THEN 'G'
    WHEN [item_type] = 7 THEN 'C'
    WHEN [item_type] IN (20, 27, 28, 18, 19) THEN 'L'
    WHEN [item_type] IN (25, 26, 30, 31, 32, 14) THEN 'M'
    ELSE [item_type] -- Keeps the original value if no condition is met
END



print ('##########################################')
print 'Contract Split migration'
print ('##########################################')

BEGIN TRY
    BEGIN TRANSACTION;

    -- Insert new contract splits - STATZ
    INSERT INTO [dbo].[contracts_contractsplit]
           ([company_name]
           ,[split_value]
           ,[split_paid]
           ,[created_at]
           ,[modified_at]
           ,[contract_id])
    SELECT        
        'STATZ' AS company_name, 
        sc.STATZSplitDol, 
        sc.ActualSTATZDol, 
        isnull(sc.CreatedOn,SYSDATETIME()), 
        isnull(sc.ModifiedOn,isnull(sc.CreatedOn,SYSDATETIME())), 
        sc.Contract_ID 
    FROM            
        ContractLog.dbo.STATZ_SUB_CONTRACTS_TBL sc
    INNER JOIN [ContractLog].[dbo].[STATZ_CONTRACTS_TBL] c ON sc.Contract_ID = c.ID
    INNER JOIN [contracts_contract] cc ON c.ID = cc.id;


    -- Insert new contract splits - PPI
    INSERT INTO [dbo].[contracts_contractsplit]
           ([company_name]
           ,[split_value]
           ,[split_paid]
           ,[created_at]
           ,[modified_at]
           ,[contract_id])
    SELECT        
        'PPI' AS company_name, 
        sc.PPISplitDol, 
        sc.ActualPaidPPIDol, 
        isnull(sc.CreatedOn,SYSDATETIME()), 
        isnull(sc.ModifiedOn,isnull(sc.CreatedOn,SYSDATETIME())), 
        sc.Contract_ID 
    FROM            
        ContractLog.dbo.STATZ_SUB_CONTRACTS_TBL sc
    INNER JOIN [ContractLog].[dbo].[STATZ_CONTRACTS_TBL] c ON sc.Contract_ID = c.ID
    INNER JOIN [contracts_contract] cc ON c.ID = cc.id;


    -- Insert new contract splits - DGCI
    INSERT INTO [dbo].[contracts_contractsplit]
           ([company_name]
           ,[split_value]
           ,[split_paid]
           ,[created_at]
           ,[modified_at]
           ,[contract_id])
    SELECT        
        'DGCI' AS company_name, 
        sc.DGCISplitDol, 
        sc.ActualPaidDGCIDol, 
        isnull(sc.CreatedOn,SYSDATETIME()), 
        isnull(sc.ModifiedOn,isnull(sc.CreatedOn,SYSDATETIME())), 
        sc.Contract_ID 
    FROM            
        ContractLog.dbo.STATZ_SUB_CONTRACTS_TBL sc
    INNER JOIN [ContractLog].[dbo].[STATZ_CONTRACTS_TBL] c ON sc.Contract_ID = c.ID
    INNER JOIN [contracts_contract] cc ON c.ID = cc.id;

    -- Delete Records from split table where split value and split paid are null
    DELETE FROM [dbo].[contracts_contractsplit]
    WHERE isnull([split_value],0.00) = 0.00 AND isnull([split_paid],0.00) = 0.00;


    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;
    -- print 'Error migrating contract splits: ' + ERROR_MESSAGE();
END CATCH;
GO


-- Update Planned Split and Plan Gross
print ('##########################################')
print 'Update Planned Split and Plan Gross'
print ('##########################################')

UPDATE [dbo].[contracts_contract]
SET planned_split = sc.PlanSplit_per_PPIbid
FROM [dbo].[contracts_contract] c
INNER JOIN [ContractLog].[dbo].[STATZ_SUB_CONTRACTS_TBL] sc ON c.id = sc.Contract_ID;

--Update Plan Gross
UPDATE [dbo].[contracts_contract]
SET plan_gross = sc.PlanGrossDol
FROM [dbo].[contracts_contract] c
INNER JOIN [ContractLog].[dbo].[STATZ_SUB_CONTRACTS_TBL] sc ON c.id = sc.Contract_ID;



-- Pay History migration
-- Still need to convert the payment type to the new data.
print ('##########################################')
print 'Pay History migration'
print ('##########################################')
INSERT INTO [dbo].[contracts_paymenthistory]
           ([payment_type]
           ,[payment_amount]
           ,[payment_date]
           ,[payment_info]
           ,[clin_id]
           ,[created_at]
           ,[updated_at]
           ,[created_by_id]
           ,[updated_by_id])
SELECT case when [PaymentType] = 'SubPO' then 'quote_value'
        when [PaymentType] = 'SubPaid' then 'paid_amount' 
        when [PaymentType] = 'Contract' then 'contract_value' 
        when [PaymentType] = 'WAWFPayment' then 'wawf_payment' 
        when [PaymentType] = 'PlanGross' then 'plan_gross' 
        when [PaymentType] = 'PaidPPI' then 'statz_split_paid' 
        when [PaymentType] = 'PaidSTATZ' then 'ppi_split_paid'
        when [PaymentType] = 'Interest' then 'special_payment_terms_interest' 
        else null end as [payment_type]
      ,[PaymentAmount]
      ,[PaymentDate]
      ,[PaymentInfo]
	  ,[SubContract_ID]
	  ,ISNULL(ph.CreatedOn, SYSDATETIME()) AS created_at
	  ,ISNULL(ph.CreatedOn, SYSDATETIME()) AS updated_at
      ,ISNULL(um_created.user_id, 1) AS created_by_id
      ,ISNULL(um_created.user_id, 1) AS updated_by_id
FROM [ContractLog].[dbo].[STATZ_PAY_HIST_TBL] ph
JOIN contracts_clin c ON ph.[SubContract_ID] = c.id
LEFT JOIN #UserMapping um_created ON ph.CreatedBy = um_created.username
WHERE ph.[PaymentType] in ('SubPO', 'SubPaid', 'Contract', 'WAWFPayment', 'PlanGross', 'PaidPPI', 'PaidSTATZ', 'Interest');


-- Add Quote Value to Payment History
INSERT INTO [dbo].[contracts_paymenthistory]
           ([payment_type]
           ,[payment_amount]
           ,[payment_date]
           ,[payment_info]
           ,[clin_id]
           ,[created_at]
           ,[updated_at]
           ,[created_by_id]
           ,[updated_by_id])
SELECT 'item_value' as [payment_type]
      ,isnull(sc.ContractDol,0.00) as ContractDol
      ,c.[Award Date]
      ,'migrated data'
	  ,sc.[ID]
	  ,ISNULL(sc.CreatedOn, SYSDATETIME()) AS created_at
	  ,ISNULL(sc.CreatedOn, SYSDATETIME()) AS updated_at
      ,1 AS created_by_id
      ,1 AS updated_by_id
FROM [ContractLog].[dbo].[STATZ_SUB_CONTRACTS_TBL] sc
INNER JOIN [ContractLog].[dbo].[STATZ_CONTRACTS_TBL] c ON sc.Contract_ID = c.ID;



-- Note migration
print ('##########################################')
print 'Note migration'
print ('##########################################')

BEGIN TRY
    DECLARE @RowCount INT;
    DECLARE @ErrorMessage NVARCHAR(MAX);
    
    BEGIN TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF before setting it ON
    SET IDENTITY_INSERT [dbo].[contracts_note] ON;
    
    INSERT INTO contracts_note (
        id,
        content_type_id,
        object_id,
        note,
        created_by_id,
        created_on,
        modified_by_id,
        modified_on
    )
    SELECT 
        n.ID,
        CASE n.Type
            WHEN 'cont' THEN 18  -- Contract content type ID
            WHEN 'sub' THEN 12   -- CLIN content type ID
            ELSE NULL
        END,
        n.Ref_ID,
        n.Note,
        ISNULL(um_created.user_id, 1) AS created_by_id,
        ISNULL(n.CreatedOn, SYSDATETIME()) AS created_on,
        ISNULL(um_modified.user_id, 1) AS modified_by_id,
        ISNULL(n.ModifiedOn, SYSDATETIME()) AS modified_on
    FROM ContractLog.dbo.STATZ_NOTES_TBL n
    LEFT JOIN #UserMapping um_created ON n.CreatedBy = um_created.username
    LEFT JOIN #UserMapping um_modified ON n.ModifiedBy = um_modified.username
    WHERE n.Type IN ('cont', 'sub');
    
    SET @RowCount = @@ROWCOUNT;
    
    SET IDENTITY_INSERT [dbo].[contracts_note] OFF;
    
    COMMIT TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF after operation
    
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;
    
    SET @ErrorMessage = ERROR_MESSAGE();
    -- print 'Error migrating notes: ' + @ErrorMessage;
END CATCH;
GO

-- Reminder migration
print ('##########################################')
print 'Reminder migration'
print ('##########################################')

BEGIN TRY
    DECLARE @RowCount INT;
    DECLARE @ErrorMessage NVARCHAR(MAX);
    
    BEGIN TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF before setting it ON
    SET IDENTITY_INSERT [dbo].[contracts_reminder] ON;
    
    INSERT INTO contracts_reminder (
        id, reminder_title, reminder_text, reminder_date, reminder_user_id,
        reminder_completed, reminder_completed_date, reminder_completed_user_id,
        note_id
    )
    SELECT  r.ID AS id, 
            r.Heading AS reminder_title, 
            r.Details AS reminder_text, 
            r.ReminderDate AS reminder_date, 
            ISNULL(um_reminder.user_id, 1) AS reminder_user_id, 
            r.Completed AS reminder_completed, 
            r.DateCompleted AS reminder_completed_date, 
            ISNULL(um_completed.user_id, 1) AS reminder_completed_user_id, 
            r.Notes_ID AS note_id
    FROM ContractLog.dbo.STATZ_REMINDERS_TBL AS r 
    LEFT JOIN #UserMapping um_reminder ON r.ReminderUser = um_reminder.username
    LEFT JOIN #UserMapping um_completed ON r.CompletedBy = um_completed.username
    WHERE r.Notes_ID IS NULL;


    INSERT INTO contracts_reminder (
        id, reminder_title, reminder_text, reminder_date, reminder_user_id,
        reminder_completed, reminder_completed_date, reminder_completed_user_id,
        note_id
    )
    SELECT  r.ID AS id, 
            r.Heading AS reminder_title, 
            r.Details AS reminder_text, 
            r.ReminderDate AS reminder_date, 
            ISNULL(um_reminder.user_id, 1) AS reminder_user_id, 
            r.Completed AS reminder_completed, 
            r.DateCompleted AS reminder_completed_date, 
            ISNULL(um_completed.user_id, 1) AS reminder_completed_user_id, 
            r.Notes_ID AS note_id
    FROM ContractLog.dbo.STATZ_REMINDERS_TBL AS r 
    JOIN ContractLog.[dbo].[STATZ_NOTES_TBL] as notes ON r.Notes_ID = notes.id
    LEFT JOIN #UserMapping um_reminder ON r.ReminderUser = um_reminder.username
    LEFT JOIN #UserMapping um_completed ON r.CompletedBy = um_completed.username
    WHERE r.Notes_ID IS NOT NULL;

    SET @RowCount = @@ROWCOUNT;
    
    SET IDENTITY_INSERT [dbo].[contracts_reminder] OFF;
    
    COMMIT TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF after operation
    
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;
    
    SET @ErrorMessage = ERROR_MESSAGE();
    -- print 'Error migrating reminders: ' + @ErrorMessage;
END CATCH;
GO

-- FolderTracking migration
print ('##########################################')
print 'FolderTracking migration'
print ('##########################################')

BEGIN TRY
    DECLARE @RowCount INT;
    DECLARE @ErrorMessage NVARCHAR(MAX);
    
    BEGIN TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF before setting it ON
    SET IDENTITY_INSERT [dbo].[contracts_foldertracking] ON;
    
    INSERT INTO contracts_foldertracking (
        id, stack, contract_id, partial, rts_email, qb_inv, wawf,
        wawf_qar, vsm_scn, sir_scn, tracking, tracking_number,
        sort_data, note, highlight, closed, date_added, date_closed,
        added_by_id, closed_by_id, created_on, modified_on, created_by_id, modified_by_id
    )
    SELECT 
        ft.ID AS id,
        isnull(ft.Stack, '0 - NONE') AS stack,
        ft.ContractID AS contract_id,
        ft.Partial AS partial,
        ft.RTS_Email AS rts_email,
        ft.QB_INV AS qb_inv,
        ft.WAWF AS wawf,
        ft.WAWF_QAR AS wawf_qar,
        ft.VSM_SCN AS vsm_scn,
        NULL AS sir_scn,  -- New field, no source data
        ft.TrackingType AS tracking,
        ft.TrackingNum AS tracking_number,
        ft.Sort_Data AS sort_data,
        ft.Note AS note,
        ft.Highlight AS highlight,
        ft.[Close] AS closed,
        DATEADD(day, -1, GETDATE()) AS date_added,  -- Yesterday
        CASE WHEN ft.[Close] = 1 THEN GETDATE() ELSE NULL END AS date_closed,
        (SELECT user_id FROM #UserMapping WHERE username = 'system') AS added_by_id,
        CASE WHEN ft.[Close] = 1 THEN (SELECT user_id FROM #UserMapping WHERE username = 'system') ELSE NULL END AS closed_by_id,
        SYSDATETIME() AS created_on,
        SYSDATETIME() AS modified_on,
        1 AS created_by_id,
        1 AS modified_by_id
    FROM ContractLog.dbo.STATZ_FOLDER_TRACKING_TBL ft

    
    SET @RowCount = @@ROWCOUNT;
    
    SET IDENTITY_INSERT [dbo].[contracts_foldertracking] OFF;
    
    COMMIT TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF after operation
    
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;
    
    SET @ErrorMessage = ERROR_MESSAGE();
    -- print 'Error migrating folder tracking: ' + @ErrorMessage;
END CATCH;
GO

-- Expedite migration
print ('##########################################')
print 'Expedite migration'
print ('##########################################')

BEGIN TRY
    DECLARE @RowCount INT;
    DECLARE @ErrorMessage NVARCHAR(MAX);
    
    BEGIN TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF before setting it ON
    SET IDENTITY_INSERT [dbo].[contracts_expedite] ON;
    
    INSERT INTO contracts_expedite (
        [id],
        [contract_id],
        [initiated],
        [initiateddate],
        [initiatedby_id],
        [successful],
        [successfuldate],
        [successfulby_id],
        [used],
        [useddate],
        [usedby_id]
    )
    SELECT  ex.ID, 
        sub.Contract_ID, 
        ex.Initiated, 
        ex.InitiatedDate, 
        ISNULL(um_initiated.user_id, 1) AS initiatedby_id,
        ex.Successful, 
        ex.SuccessfulDate, 
        ISNULL(um_successful.user_id, 1) AS successfulby_id,
        ex.Used, 
        ex.UsedDate, 
        ISNULL(um_used.user_id, 1) AS usedby_id
    FROM  ContractLog.dbo.STATZ_EXPEDITES_TBL AS ex 
    INNER JOIN ContractLog.dbo.STATZ_SUB_CONTRACTS_TBL AS sub ON ex.SubID = sub.ID
    LEFT JOIN #UserMapping um_initiated ON ex.InitiatedBy = um_initiated.username
    LEFT JOIN #UserMapping um_successful ON ex.SuccessfulBy = um_successful.username
    LEFT JOIN #UserMapping um_used ON ex.UsedBy = um_used.username
    
    SET @RowCount = @@ROWCOUNT;
    
    SET IDENTITY_INSERT [dbo].[contracts_expedite] OFF;
    
    COMMIT TRANSACTION;
    
    EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF after operation
    
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;
    
    SET @ErrorMessage = ERROR_MESSAGE();
    -- print 'Error migrating expedites: ' + @ErrorMessage;
END CATCH;
GO

-- InventoryItem migration
print ('##########################################')
print 'InventoryItem migration'
print ('##########################################')

INSERT INTO STATZ_WAREHOUSE_INVENTORY_TBL (
    nsn, description, partnumber, manufacturer, itemlocation,
    quantity, purchaseprice, totalcost
)
SELECT 
    NSN AS nsn,
    Description AS description,
    PartNumber AS partnumber,
    Manufacturer AS manufacturer,
    ItemLocation AS itemlocation,
    Quantity AS quantity,
    PurchasePrice AS purchaseprice,
    TotalCost AS totalcost
FROM ContractLog.dbo.STATZ_WAREHOUSE_INVENTORY_TBL;


-- AccessLog Visitor migration
print ('##########################################')
print 'AccessLog Visitor migration'
print ('##########################################')

INSERT INTO accesslog_visitor (
    date_of_visit, visitor_name, visitor_company,
    reason_for_visit, is_us_citizen, time_in, time_out,
    departed
)
SELECT 
    DateOfVisit AS date_of_visit,
    VisitorName AS visitor_name,
    VisitorCompany AS visitor_company,
    ResonForVisit AS reason_for_visit,
    1 AS is_us_citizen,
    TimeArrived AS time_in,
    TimeDepart AS time_out,
    Departed AS departed
FROM CommonCore.dbo.STATZ_VISITOR_LOG;


-- AccessLog Staged migration
print ('##########################################')
print 'AccessLog Staged migration'
print ('##########################################')

INSERT INTO accesslog_staged (
    visitor_name, visitor_company, reason_for_visit,
    is_us_citizen, date_added
)
SELECT 
    Name AS visitor_name,
    Company AS visitor_company,
    ReasonForVisit AS reason_for_visit,
    0 AS is_us_citizen,
    CAST(timestamp AS DATETIME) AS date_added
FROM CommonCore.dbo.STATZ_VISITOR_LOG_GUEST_TBL;


-- ClinAcknowledgment migration
print ('##########################################')
print 'ClinAcknowledgment migration'
print ('##########################################')

EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF before setting it ON
SET IDENTITY_INSERT [dbo].[contracts_clinacknowledgment] ON;
INSERT INTO contracts_clinacknowledgment (
    id, clin_id, po_to_supplier_bool, po_to_supplier_date, po_to_supplier_user_id,
    clin_reply_bool, clin_reply_date, clin_reply_user_id, po_to_qar_bool, po_to_qar_date,
    po_to_qar_user_id, created_on, modified_on, created_by_id, modified_by_id
)
SELECT 
    a.ID AS id,
    a.SubID AS clin_id,
    a.POToSub_Bool AS po_to_supplier_bool,
    isnull(a.POToSub_Date, SYSDATETIME()) AS po_to_supplier_date,
    isnull(um_po_supplier.user_id, 1) AS po_to_supplier_user_id,
    a.SubReply_Bool AS clin_reply_bool,
    isnull(a.SubReply_Date, SYSDATETIME()) AS clin_reply_date,
    isnull(um_clin_reply.user_id, 1) AS clin_reply_user_id,
    a.POToQAR_Bool AS po_to_qar_bool,
    isnull(a.POToQAR_Date, SYSDATETIME()) AS po_to_qar_date,
    isnull(um_po_qar.user_id, 1) AS po_to_qar_user_id,
    SYSDATETIME() AS created_on,
    SYSDATETIME() AS modified_on,
    1 AS created_by_id,
    1 AS modified_by_id
FROM ContractLog.dbo.STATZ_ACKNOWLEDGMENT_TBL a
LEFT JOIN #UserMapping um_po_supplier ON a.POToSub_User = um_po_supplier.username
LEFT JOIN #UserMapping um_po_qar ON a.POToQAR_User = um_po_qar.username
LEFT JOIN #UserMapping um_clin_reply ON a.SubReply_User = um_clin_reply.username
INNER JOIN contracts_clin AS c ON a.SubID = c.id;

SET IDENTITY_INSERT [dbo].[contracts_clinacknowledgment] OFF;
EXEC #EnsureIdentityInsertOff;  -- Ensure IDENTITY_INSERT is OFF after operation

-- AcknowledgementLetter migration
print ('##########################################')
print 'AcknowledgementLetter migration'
print ('##########################################')

BEGIN TRY
    DECLARE @RowCount INT;
    DECLARE @ErrorMessage NVARCHAR(MAX);
    
    BEGIN TRANSACTION;
        
    INSERT INTO [dbo].[contracts_acknowledgementletter]
           ([created_on]
           ,[modified_on]
           ,[letter_date]
           ,[salutation]
           ,[addr_fname]
           ,[addr_lname]
           ,[supplier]
           ,[st_address]
           ,[city]
           ,[state]
           ,[zip]
           ,[po]
           ,[po_ext]
           ,[contract_num]
           ,[fat_plt_due_date]
           ,[supplier_due_date]
           ,[dpas_priority]
           ,[statz_contact]
           ,[statz_contact_title]
           ,[statz_contact_phone]
           ,[statz_contact_email]
           ,[created_by_id]
           ,[modified_by_id]
           ,[clin_id])
SELECT        GETDATE() AS created_on, GETDATE() AS modified_on, al.[LETTER DATE] AS letter_date, al.SALUTATION AS salutation, al.ADDR_FNAME AS addr_fname, 
                         al.ADDR_LNAME AS addr_lname, al.Vendor AS supplier, al.ST_ADDRESS AS st_address, al.CITY AS city, 
                         al.STATE AS state, al.ZIP AS zip, al.PO AS po, al.PO_ext AS po_ext, al.ContractNum AS contract_num, 
                         al.FAT_PLTDueDate AS fat_plt_due_date, al.VendorDueDate AS supplier_due_date, al.DPASPriority AS dpas_priority, 
                         al.StatzContact AS statz_contact, al.StatzContactTitle AS statz_contact_title, al.StatzContactPhone AS statz_contact_phone, 
                         al.StatzContactEmail AS statz_contact_email, 1 AS created_by_id, 1 AS modified_by_id, sub.ID
FROM            ContractLog.dbo.STATZ_ACK_LETTER_TBL as al INNER JOIN
                         ContractLog.dbo.STATZ_SUB_CONTRACTS_TBL as sub ON al.SubID = sub.ID

    
    SET @RowCount = @@ROWCOUNT;
    
    
    COMMIT TRANSACTION;
    
    
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;
    
    SET @ErrorMessage = ERROR_MESSAGE();
    -- print 'Error migrating acknowledgement letters: ' + @ErrorMessage;
END CATCH;
GO

-- migrate idiq_contract
print ('##########################################')
print 'migrate idiq_contract'
print ('##########################################')

SET IDENTITY_INSERT [dbo].[contracts_idiqcontract] ON;

    INSERT INTO [dbo].[contracts_idiqcontract]
            ([id]
            ,[created_on]
            ,[modified_on]
            ,[contract_number]
            ,[award_date]
            ,[term_length]
            ,[option_length]
            ,[closed]
            ,[buyer_id]
            ,[created_by_id]
            ,[modified_by_id]
            ,[tab_num])
    SELECT [ID]
        ,SYSDATETIME()
        ,SYSDATETIME()
        ,[ContractNum]
        ,[AwardDate]
        ,[TermLength]
        ,[OptionLength]
        ,[IDIQClosed]
        ,[BuyerID]
        ,1
        ,1
        ,[TabNum]
    FROM [ContractLog].[dbo].[STATZ_IDIQ_TBL];

SET IDENTITY_INSERT [dbo].[contracts_idiqcontract] OFF;



-- migrate idiq_contractdetails
print ('##########################################')
print 'migrate idiq_contractdetails'
print ('##########################################')

INSERT INTO [dbo].[contracts_idiqcontractdetails]
           ([idiq_contract_id]
           ,[nsn_id]
           ,[supplier_id])
SELECT        ContractLog.dbo.STATZ_IDIQ_CONTRACT_DETAILS.IDIQ_ID, ContractLog.dbo.STATZ_IDIQ_CONTRACT_DETAILS.NSNID, ContractLog.dbo.STATZ_IDIQ_CONTRACT_DETAILS.SUPPLIERID
FROM            ContractLog.dbo.STATZ_IDIQ_CONTRACT_DETAILS INNER JOIN
                         contracts_idiqcontract ON ContractLog.dbo.STATZ_IDIQ_CONTRACT_DETAILS.IDIQ_ID = contracts_idiqcontract.id INNER JOIN
                         contracts_nsn ON ContractLog.dbo.STATZ_IDIQ_CONTRACT_DETAILS.NSNID = contracts_nsn.id INNER JOIN
                         contracts_supplier ON ContractLog.dbo.STATZ_IDIQ_CONTRACT_DETAILS.SUPPLIERID = contracts_supplier.id



print ('##########################################')
print 'reseed tables'
print ('##########################################')

GO

-- Address reseeding
DECLARE @max_id INT;
SELECT @max_id = MAX(id) FROM contracts_address;
IF @max_id IS NOT NULL
    DBCC CHECKIDENT ('contracts_address', RESEED, @max_id);
GO

-- Contact reseeding
DECLARE @max_id INT;
SELECT @max_id = MAX(id) FROM contracts_contact;
IF @max_id IS NOT NULL
    DBCC CHECKIDENT ('contracts_contact', RESEED, @max_id);
GO

-- NSN reseeding
DECLARE @max_id INT;
SELECT @max_id = MAX(id) FROM contracts_nsn;
IF @max_id IS NOT NULL
    DBCC CHECKIDENT ('contracts_nsn', RESEED, @max_id);
GO

-- Supplier reseeding
DECLARE @max_id INT;
SELECT @max_id = MAX(id) FROM contracts_supplier;
IF @max_id IS NOT NULL
    DBCC CHECKIDENT ('contracts_supplier', RESEED, @max_id);
GO

-- Contract reseeding
DECLARE @max_id INT;
SELECT @max_id = MAX(id) FROM contracts_contract;
IF @max_id IS NOT NULL
    DBCC CHECKIDENT ('contracts_contract', RESEED, @max_id);
GO

-- CLIN reseeding
DECLARE @max_id INT;
SELECT @max_id = MAX(id) FROM contracts_clin;
IF @max_id IS NOT NULL
    DBCC CHECKIDENT ('contracts_clin', RESEED, @max_id);
GO

-- Note reseeding
DECLARE @max_id INT;
SELECT @max_id = MAX(id) FROM contracts_note;
IF @max_id IS NOT NULL
    DBCC CHECKIDENT ('contracts_note', RESEED, @max_id);
GO

-- Reminder reseeding
DECLARE @max_id INT;
SELECT @max_id = MAX(id) FROM contracts_reminder;
IF @max_id IS NOT NULL
    DBCC CHECKIDENT ('contracts_reminder', RESEED, @max_id);
GO

-- FolderTracking reseeding
DECLARE @max_id INT;
SELECT @max_id = MAX(id) FROM contracts_foldertracking;
IF @max_id IS NOT NULL
    DBCC CHECKIDENT ('contracts_foldertracking', RESEED, @max_id);
GO

-- Expedite reseeding
DECLARE @max_id INT;
SELECT @max_id = MAX(id) FROM contracts_expedite;
IF @max_id IS NOT NULL
    DBCC CHECKIDENT ('contracts_expedite', RESEED, @max_id);
GO

-- InventoryItem reseeding
DECLARE @max_id INT;
SELECT @max_id = MAX(id) FROM STATZ_WAREHOUSE_INVENTORY_TBL;
IF @max_id IS NOT NULL
    DBCC CHECKIDENT ('STATZ_WAREHOUSE_INVENTORY_TBL', RESEED, @max_id);
GO

-- Visitor reseeding
DECLARE @max_id INT;
SELECT @max_id = MAX(id) FROM accesslog_visitor;
IF @max_id IS NOT NULL
    DBCC CHECKIDENT ('accesslog_visitor', RESEED, @max_id);
GO

-- Staged reseeding
DECLARE @max_id INT;
SELECT @max_id = MAX(id) FROM accesslog_staged;
IF @max_id IS NOT NULL
    DBCC CHECKIDENT ('accesslog_staged', RESEED, @max_id);
GO


-- Clean up temporary tables
IF OBJECT_ID('tempdb..#UserMapping') IS NOT NULL
    DROP TABLE #UserMapping;
IF OBJECT_ID('tempdb..#AddressMapping') IS NOT NULL
    DROP TABLE #AddressMapping;
GO

-- Final cleanup
DROP PROCEDURE #EnsureIdentityInsertOff;
GO 


-- Update contract values
print ('##########################################')
print 'Update contract values'
print ('##########################################')

UPDATE       contracts_contract
SET                contract_value = subquery.NewTotal, plan_gross = subquery.planGross
FROM            (SELECT        ISNULL(SUM(ContractDol), 0.00) AS NewTotal, Contract_ID, ISNULL(SUM(PlanGrossDol), 0.00) AS planGross
                          FROM            ContractLog.dbo.STATZ_SUB_CONTRACTS_TBL
                          GROUP BY Contract_ID) AS subquery INNER JOIN
                         contracts_contract ON subquery.Contract_ID = contracts_contract.id

-- Update planned split
print ('##########################################')
print 'Update planned split'
print ('##########################################')

UPDATE       contracts_contract
SET                [planned_split] = PlanSplit_per_PPIbid
FROM            (SELECT        Contract_ID, PlanSplit_per_PPIbid, Type_ID
				FROM            ContractLog.dbo.STATZ_SUB_CONTRACTS_TBL
				WHERE        (Type_ID = 1)) AS subquery INNER JOIN
                         contracts_contract ON subquery.Contract_ID = contracts_contract.id


-- Update contract_contractstatus
print ('##########################################')
print 'Update contract_contractstatus'
print ('##########################################')

SET IDENTITY_INSERT [dbo].[contracts_contractstatus] ON;

INSERT INTO contracts_contractstatus (id, description)
VALUES (1, 'Open'),
       (2, 'Closed'),
       (3, 'Canceled');

SET IDENTITY_INSERT [dbo].[contracts_contractstatus] OFF;


-- Update contract status
print ('##########################################')
print 'Update contract status'
print ('##########################################')

UPDATE contracts_contract
SET status_id = CASE
    WHEN cancelled = 1 THEN 3
    WHEN cancelled = 0 AND [open] = 0 THEN 2
    WHEN cancelled = 0 AND [open] = 1 THEN 1
END;


-- Update idiq contract id
print ('##########################################')
print 'Update idiq contract id'
print ('##########################################')

UPDATE dbo.contracts_contract
SET idiq_contract_id = STATZ_IDIQ_CONTRACTS_TBL.IDIQ_ID
FROM dbo.contracts_contract AS cc
INNER JOIN [ContractLog].dbo.STATZ_IDIQ_CONTRACTS_TBL ON cc.id = STATZ_IDIQ_CONTRACTS_TBL.Contract_ID

-- Update clin item number
print ('##########################################')
print 'Update clin item number'
print ('##########################################')

;WITH NumberedCLINs AS (
    SELECT 
        contract_id,
        id,
        clin_type_id,
        ROW_NUMBER() OVER (PARTITION BY contract_id ORDER BY id) AS row_num,
        CASE 
            WHEN clin_type_id = 1 THEN 1
            WHEN clin_type_id IN (17, 27, 18, 7, 20, 19, 28) THEN 2
            WHEN clin_type_id IN (2, 15) THEN 3
            WHEN clin_type_id = 25 THEN 100
            WHEN clin_type_id IN (14, 24, 26, 29, 30, 31, 32) THEN 101
            ELSE 999 -- Default case, if needed
        END AS initial_number
    FROM contracts_clin
),
FormattedCLINs AS (
    SELECT 
        contract_id,
        id,
        clin_type_id,
        initial_number,
        ROW_NUMBER() OVER (PARTITION BY contract_id, initial_number ORDER BY id) AS seq_num
    FROM NumberedCLINs
)
UPDATE contracts_clin
SET item_number = RIGHT('0000' + CAST(FormattedCLINs.initial_number + FormattedCLINs.seq_num - 1 AS VARCHAR), 4)
FROM FormattedCLINs
WHERE contracts_clin.id = FormattedCLINs.id;



-- Update folder tracking closed status
print ('##########################################')
print 'Update folder tracking closed status'
print ('##########################################')

UPDATE       contracts_foldertracking
SET                closed = 1
WHERE        (stack = N'CLOSE');



