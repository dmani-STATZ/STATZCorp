from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ('contracts', 'create_nsn_view'),  # Make sure this depends on the previous migration
    ]

    operations = [
        # Add simple indexes for common search patterns
        migrations.RunSQL(
            """
            -- Add simple indexes for common search patterns
            -- Note: We cannot include 'description' in an index because it's NVARCHAR(MAX)
            IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_nsn_code' AND object_id = OBJECT_ID('contracts_nsn'))
                CREATE INDEX idx_nsn_code ON contracts_nsn (nsn_code);
            
            IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_nsn_part_number' AND object_id = OBJECT_ID('contracts_nsn'))
                CREATE INDEX idx_nsn_part_number ON contracts_nsn (part_number);
            """,
            """
            -- Drop indexes
            IF EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_nsn_code' AND object_id = OBJECT_ID('contracts_nsn'))
                DROP INDEX idx_nsn_code ON contracts_nsn;
            
            IF EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_nsn_part_number' AND object_id = OBJECT_ID('contracts_nsn'))
                DROP INDEX idx_nsn_part_number ON contracts_nsn;
            """
        ),
        
        # Note about full-text search
        migrations.RunSQL(
            """
            -- Note: For efficient searching of text columns like 'description',
            -- full-text search is recommended. However, it requires SQL Server
            -- with Full-Text Search installed and appropriate permissions.
            --
            -- If full-text search is not available, you can still search using
            -- LIKE or CONTAINS operators, but performance may be slower.
            """,
            "-- No reverse SQL needed for comments"
        )
    ] 