# Contracts App - Modular Views Structure

This directory contains the modular views for the Contracts app. Each file contains views related to a specific aspect of the application.

## File Structure

- `__init__.py` - Imports all views from the modular structure to make them available at the package level
- `contract_views.py` - Views for contract creation, updating, and management
- `clin_views.py` - Views for CLIN (Contract Line Item Number) management
- `supplier_views.py` - Views for supplier management
- `nsn_views.py` - Views for NSN (National Stock Number) management
- `note_views.py` - Views for note management
- `reminder_views.py` - Views for reminder management
- `acknowledgement_letter_views.py` - Views for acknowledgement letter generation and management
- `dashboard_views.py` - Views for the contract lifecycle dashboard
- `contract_log_views.py` - Views for contract log and export functionality
- `dd1155_views.py` - Views for DD1155 form processing

## Usage

All views are imported in the `__init__.py` file, so they can be accessed from the parent package:

```python
from contracts.views import ContractDetailView, ClinCreateView, etc.
```

## Benefits of Modular Structure

1. **Improved Code Organization**: Each file contains views related to a specific feature or entity
2. **Better Maintainability**: Easier to find and modify specific views
3. **Enhanced Collaboration**: Multiple developers can work on different view files simultaneously
4. **Reduced File Size**: Smaller files are easier to navigate and understand
5. **Focused Testing**: Test files can be organized to match the view structure

## Migration from Monolithic Structure

The original `views.py` file has been replaced with this modular structure. All views have been moved to their respective files without changing their functionality.

To update the project to use this new structure:

1. Ensure all imports in `urls.py` are updated to import from the new structure
2. Update any direct imports of views in other parts of the codebase 