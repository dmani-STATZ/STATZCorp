from django.db import connection

def create_app_registry_table():
    """Manually create the AppRegistry table in SQL Server"""
    cursor = connection.cursor()
    
    # Check if table exists
    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[users_appregistry]') AND type in (N'U'))
        BEGIN
            CREATE TABLE [dbo].[users_appregistry] (
                [id] [int] IDENTITY(1,1) NOT NULL,
                [app_name] [nvarchar](100) NOT NULL,
                [display_name] [nvarchar](200) NOT NULL,
                [is_active] [bit] NOT NULL,
                [created_at] [datetime2](7) NOT NULL,
                [updated_at] [datetime2](7) NOT NULL,
                CONSTRAINT [PK_users_appregistry] PRIMARY KEY CLUSTERED ([id] ASC),
                CONSTRAINT [users_appregistry_app_name_unique] UNIQUE NONCLUSTERED ([app_name] ASC)
            )
            
            PRINT 'Table users_appregistry created.'
        END
        ELSE
        BEGIN
            PRINT 'Table users_appregistry already exists.'
        END
    """)
    connection.commit()
    
    # Insert demo data
    from users.models import AppRegistry
    AppRegistry.register_apps_from_system()
    print("App registry updated with system apps")
    
if __name__ == "__main__":
    create_app_registry_table() 