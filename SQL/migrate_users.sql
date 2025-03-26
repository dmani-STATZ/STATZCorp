USE [STATZWeb_dev]
GO

	SET IDENTITY_INSERT [STATZWeb].[dbo].[auth_user] ON;

	INSERT INTO [STATZWeb].[dbo].[auth_user]
			   ([id]
			   ,[password]
			   ,[last_login]
			   ,[is_superuser]
			   ,[username]
			   ,[first_name]
			   ,[last_name]
			   ,[email]
			   ,[is_staff]
			   ,[is_active]
			   ,[date_joined])
	SELECT [id]
		  ,[password]
		  ,[last_login]
		  ,[is_superuser]
		  ,[username]
		  ,[first_name]
		  ,[last_name]
		  ,[email]
		  ,[is_staff]
		  ,[is_active]
		  ,[date_joined]
	FROM [STATZWeb_dev].[dbo].[auth_user]

	SET IDENTITY_INSERT [STATZWeb].[dbo].[auth_user] OFF;
GO

--     SET IDENTITY_INSERT [STATZWeb].[dbo].[auth_permission] ON;

--     INSERT INTO [STATZWeb].[dbo].[auth_permission]
--             ([id]
--             ,[name]
--             ,[content_type_id]
--             ,[codename])
--     SELECT [id]
--         ,[name]
--         ,[content_type_id]
--         ,[codename]
--     FROM [STATZWeb_dev].[dbo].[auth_permission]

--     SET IDENTITY_INSERT [STATZWeb].[dbo].[auth_permission] OFF;
-- GO

    SET IDENTITY_INSERT [STATZWeb].[dbo].[users_apppermission] ON;

    INSERT INTO [STATZWeb].[dbo].[users_apppermission]
            ([id]
            ,[app_name_id]
            ,[has_access]
            ,[user_id])
    SELECT [id]
        ,[app_name_id]
        ,[has_access]
        ,[user_id]
    FROM [STATZWeb_dev].[dbo].[users_apppermission]

SET IDENTITY_INSERT [STATZWeb].[dbo].[users_apppermission] OFF;
GO

    SET IDENTITY_INSERT [STATZWeb].[dbo].[users_appregistry] ON;
    INSERT INTO [STATZWeb].[dbo].[users_appregistry]
            ([id]
            ,[app_name]
            ,[display_name]
            ,[is_active]
            ,[created_at]
            ,[updated_at])
    SELECT [id]
        ,[app_name]
        ,[display_name]
        ,[is_active]
        ,[created_at]
        ,[updated_at]
    FROM [STATZWeb_dev].[dbo].[users_appregistry]

SET IDENTITY_INSERT [STATZWeb].[dbo].[users_appregistry] OFF;
GO
