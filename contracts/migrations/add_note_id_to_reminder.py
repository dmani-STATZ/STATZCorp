from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0001_initial'),  # Adjust this to your latest migration
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            IF NOT EXISTS (
                SELECT * FROM sys.columns 
                WHERE object_id = OBJECT_ID(N'[dbo].[contracts_reminder]') 
                AND name = 'note_id'
            )
            BEGIN
                -- Get the data type of the id column in contracts_note
                DECLARE @NoteIdType nvarchar(128)
                SELECT @NoteIdType = t.name
                FROM sys.columns c
                JOIN sys.types t ON c.system_type_id = t.system_type_id
                WHERE c.object_id = OBJECT_ID(N'[dbo].[contracts_note]')
                AND c.name = 'id'
                
                -- Add the note_id column with the same data type
                DECLARE @SQL nvarchar(max)
                SET @SQL = 'ALTER TABLE [dbo].[contracts_reminder] ADD [note_id] ' + @NoteIdType + ' NULL'
                EXEC sp_executesql @SQL
                
                -- Add the foreign key constraint
                ALTER TABLE [dbo].[contracts_reminder] 
                ADD CONSTRAINT [FK_contracts_reminder_note_id] 
                FOREIGN KEY ([note_id]) 
                REFERENCES [dbo].[contracts_note] ([id]);
            END
            """,
            reverse_sql="""
            IF EXISTS (
                SELECT * FROM sys.columns 
                WHERE object_id = OBJECT_ID(N'[dbo].[contracts_reminder]') 
                AND name = 'note_id'
            )
            BEGIN
                IF EXISTS (
                    SELECT * FROM sys.foreign_keys
                    WHERE name = 'FK_contracts_reminder_note_id'
                )
                BEGIN
                    ALTER TABLE [dbo].[contracts_reminder] 
                    DROP CONSTRAINT [FK_contracts_reminder_note_id];
                END
                
                ALTER TABLE [dbo].[contracts_reminder] 
                DROP COLUMN [note_id];
            END
            """
        ),
    ] 