# NSN Table Performance Optimization

This document explains the optimizations implemented to improve the performance of the NSN (National Stock Number) table, which was identified as a major bottleneck in the CLIN form loading time.

## Implemented Solutions

We've implemented several complementary approaches to optimize the NSN table performance:

### 1. Searchable, Paginated Dropdown for NSN Selection

The first approach replaces the standard Django select widget with a searchable, paginated dropdown using Select2. This significantly improves the user experience by:

- Loading only a small subset of NSN records at a time (20 by default)
- Allowing users to search for NSNs by code, description, or part number
- Implementing client-side pagination for browsing through results
- Providing a more user-friendly interface for selecting from thousands of NSN records

#### Key Components:

- **Enhanced Template (`clin_form.html`)**: 
  - Added Select2 integration for the NSN field
  - Implemented custom pagination controls
  - Added search functionality with minimum input length

- **Enhanced API Endpoint (`get_select_options`)**: 
  - Added support for pagination and searching
  - Optimized query performance with proper filtering and ordering

### 2. Materialized View for NSN Data

The second approach creates a materialized view in SQL Server that pre-computes and stores NSN data for faster retrieval. This is particularly effective for the NSN table because:

- NSN data changes infrequently
- The same NSN records are queried repeatedly
- Search operations on NSN data are common and can be optimized

#### Key Components:

- **Materialized View Model (`NsnView`)**: 
  - A read-only model that maps to a SQL Server table
  - Includes denormalized data and pre-computed search vectors
  - Has optimized indexes for common query patterns

- **Custom Migration (`create_nsn_view.py`)**: 
  - Creates the materialized view in SQL Server
  - Creates a stored procedure to refresh the view

- **Management Command (`refresh_nsn_view.py`)**: 
  - Provides a Django command to manually refresh the view
  - Useful for refreshing after bulk NSN data updates

### 3. Database Indexes and Full-Text Search

The third approach adds specialized indexes to the NSN table to improve query performance:

- Composite indexes for common search patterns
- Filtered indexes for frequently accessed subsets of data
- Full-text search index for efficient text searching (requires manual setup)

#### Key Components:

- **Custom Migration (`add_nsn_indexes.py`)**: 
  - Creates composite indexes for common search patterns
  - Adds a filtered index for active NSNs (those used in CLINs)

- **SQL Script (`setup_nsn_fulltext_and_job.sql`)**: 
  - Contains SQL commands to set up full-text search
  - Creates a SQL Agent job to refresh the view nightly
  - Must be run manually by a DBA with appropriate permissions

### 4. API Optimization for NSN Queries

The final approach optimizes the API endpoint that serves NSN data:

- Uses the materialized view when available
- Falls back to the regular model with optimized queries
- Implements efficient pagination and search filtering
- Prioritizes exact matches in search results

## How to Use

No changes are needed in how you use the CLIN form. The optimizations are transparent to users. The NSN dropdown will now:

1. Load much faster initially (showing only a small subset of data)
2. Allow searching by typing at least 2 characters
3. Show pagination controls for browsing through results
4. Provide a more user-friendly interface for selecting NSNs

## Installation and Setup

### 1. Apply Migrations

Run the migrations to create the materialized view and indexes:

```bash
python manage.py migrate
```

### 2. Manual Setup for Full-Text Search and SQL Agent Job

The full-text search index and SQL Agent job require elevated permissions and must be set up manually. A SQL script is provided for this purpose:

```bash
# Connect to your SQL Server instance and run the script
# Replace <server>, <database>, <username>, and <password> with your actual values
sqlcmd -S <server> -d <database> -U <username> -P <password> -i contracts/sql/setup_nsn_fulltext_and_job.sql
```

Alternatively, you can open the script in SQL Server Management Studio and execute it there.

### 3. Initial Data Population

After setting up the materialized view, you should populate it with the initial data:

```bash
python manage.py refresh_nsn_view
```

## Technical Details

### Materialized View Refresh

The materialized view is automatically refreshed nightly by a SQL Agent job (if set up). If you need to refresh it manually, you can use the management command:

```bash
python manage.py refresh_nsn_view
```

### Full-Text Search

The full-text search index enables efficient searching across multiple text fields. This is particularly useful for the NSN table, which contains various text fields that users might search by.

### Performance Impact

These optimizations should significantly reduce the loading time of the NSN dropdown in the CLIN form. The exact performance improvement will depend on the size of your NSN table, but you should see a noticeable difference, especially for large datasets.

## Maintenance Considerations

When making changes to the NSN model, you may need to:

1. Update the NsnView model in `models.py`
2. Refresh the materialized view using the management command
3. Update the full-text search index if the schema changes

If you add new NSN records in bulk, you should refresh the materialized view to ensure the new data is available for fast retrieval.

## Troubleshooting

### Migration Errors

If you encounter errors during migration, check the following:

1. Ensure your SQL Server user has appropriate permissions
2. Check that the SQL syntax is compatible with your SQL Server version
3. Try running the migrations one by one to isolate the issue

### Full-Text Search Issues

If full-text search is not working properly:

1. Verify that full-text search is enabled on your SQL Server instance
2. Check that the full-text catalog and index were created successfully
3. Ensure the appropriate columns are included in the full-text index

### SQL Agent Job Issues

If the SQL Agent job is not running:

1. Verify that SQL Server Agent is running
2. Check the job history for any errors
3. Ensure the job has appropriate permissions to execute the stored procedure 