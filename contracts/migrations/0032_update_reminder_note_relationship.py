from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0031_delete_idiqcontracttocontract'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            -- Drop check constraint first
            IF EXISTS (
                SELECT * FROM sys.check_constraints
                WHERE name = 'reminder_single_note_constraint'
            )
            BEGIN
                ALTER TABLE [dbo].[contracts_reminder] 
                DROP CONSTRAINT [reminder_single_note_constraint];
            END

            -- Drop indexes first
            IF EXISTS (
                SELECT * FROM sys.indexes 
                WHERE name = 'contracts_reminder_clin_note_id_a59120b7'
            )
            BEGIN
                DROP INDEX [contracts_reminder_clin_note_id_a59120b7] ON [dbo].[contracts_reminder];
            END

            IF EXISTS (
                SELECT * FROM sys.indexes 
                WHERE name = 'contracts_reminder_contract_note_id_9569a7ed'
            )
            BEGIN
                DROP INDEX [contracts_reminder_contract_note_id_9569a7ed] ON [dbo].[contracts_reminder];
            END

            -- Drop foreign key constraints
            IF EXISTS (
                SELECT * FROM sys.foreign_keys
                WHERE name = 'contracts_reminder_clin_note_id_a59120b7_fk_contracts_clinnote_id'
            )
            BEGIN
                ALTER TABLE [dbo].[contracts_reminder] 
                DROP CONSTRAINT [contracts_reminder_clin_note_id_a59120b7_fk_contracts_clinnote_id];
            END

            IF EXISTS (
                SELECT * FROM sys.foreign_keys
                WHERE name = 'contracts_reminder_contract_note_id_9569a7ed_fk_contracts_contractnote_id'
            )
            BEGIN
                ALTER TABLE [dbo].[contracts_reminder] 
                DROP CONSTRAINT [contracts_reminder_contract_note_id_9569a7ed_fk_contracts_contractnote_id];
            END

            -- Drop the columns
            IF EXISTS (
                SELECT * FROM sys.columns 
                WHERE object_id = OBJECT_ID(N'[dbo].[contracts_reminder]') 
                AND name = 'clin_note_id'
            )
            BEGIN
                ALTER TABLE [dbo].[contracts_reminder] DROP COLUMN [clin_note_id];
            END

            IF EXISTS (
                SELECT * FROM sys.columns 
                WHERE object_id = OBJECT_ID(N'[dbo].[contracts_reminder]') 
                AND name = 'contract_note_id'
            )
            BEGIN
                ALTER TABLE [dbo].[contracts_reminder] DROP COLUMN [contract_note_id];
            END

            -- Drop the old note tables
            IF EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[contracts_clinnote]') AND type in (N'U'))
            BEGIN
                DROP TABLE [dbo].[contracts_clinnote];
            END

            IF EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[contracts_contractnote]') AND type in (N'U'))
            BEGIN
                DROP TABLE [dbo].[contracts_contractnote];
            END
            """,
            reverse_sql="""
            -- Note: We don't provide reverse SQL since we're removing old tables
            -- that are no longer needed
            """
        ),
    ] 