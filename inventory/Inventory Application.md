## Inventory Application Process Write-up

**Objective:** The `inventory` application manages warehouse inventory items, providing functionalities for adding, viewing, updating, and deleting stock records.

**Key Components:**

1.  **Model (`InventoryItem`):**
    *   Located in `inventory/models.py`.
    *   Represents a single inventory item in the `STATZ_WAREHOUSE_INVENTORY_TBL` database table.
    *   Fields: `nsn`, `description`, `partnumber`, `manufacturer`, `itemlocation`, `quantity`, `purchaseprice` (all fields are nullable).
    *   Calculated Field: `totalcost` (automatically calculated as `purchaseprice * quantity` upon saving).

2.  **Form (`InventoryItemForm`):**
    *   Located in `inventory/forms.py`.
    *   Inherits from `BaseModelForm` which implements consistent form styling rules.
    *   A `ModelForm` based on the `InventoryItem` model.
    *   Excludes `id` and `totalcost` fields from user input.
    *   Uses `crispy_forms` for structured layout and styling.
    *   Includes autocomplete functionality for `nsn`, `description`, and `manufacturer` fields.

3.  **Views (`inventory/views.py`):**
    *   `dashboard`:
        *   Main view displaying all inventory items in a table format.
        *   Calculates total inventory value.
        *   Protected by `@conditional_login_required` decorator.
        *   Renders `inventory/dashboard.html`.
    *   `add_item`:
        *   Handles the creation of new inventory items.
        *   Protected by `@conditional_login_required` decorator.
        *   If `GET`, displays an empty `InventoryItemForm`.
        *   If `POST`, validates and saves the new item.
        *   Renders `inventory/item_form.html`.
    *   `edit_item`:
        *   Handles updating an existing inventory item identified by `pk`.
        *   Protected by `@conditional_login_required` decorator.
        *   Pre-fills form with existing item data.
        *   Renders `inventory/item_form.html`.
    *   `delete_item` and `delete_item_ajax`:
        *   Handles deletion of inventory items.
        *   Supports both regular and AJAX-based deletion.
        *   Protected by `@conditional_login_required` decorator.
        *   Returns JSON response for AJAX calls.
    *   Autocomplete Views:
        *   `autocomplete_nsn`
        *   `autocomplete_description`
        *   `autocomplete_manufacturer`
        *   Each returns JSON response with matching items for typeahead search.

4.  **URLs (`inventory/urls.py`):**
    *   Defines URL patterns mapping paths to views:
        *   `/`: `dashboard` (name: `dashboard`)
        *   `/add/`: `add_item` (name: `add_item`)
        *   `/edit/<int:pk>/`: `edit_item` (name: `edit_item`)
        *   `/delete-item/<int:pk>/`: `delete_item` (name: `delete_item`)
        *   `/delete-item-ajax/<int:pk>/`: `delete_item_ajax` (name: `delete_item_ajax`)
        *   `/autocomplete/nsn/`: `autocomplete_nsn`
        *   `/autocomplete/description/`: `autocomplete_description`
        *   `/autocomplete/manufacturer/`: `autocomplete_manufacturer`

5.  **Templates (`inventory/templates/inventory/`):**
    *   `dashboard.html`: Main inventory list view with Tailwind CSS styling
        *   Displays inventory items in a responsive table
        *   Shows total inventory value
        *   Includes add, edit, and delete functionality
        *   Implements AJAX-based deletion with confirmation modal
    *   `item_form.html`: Form for adding/editing items
        *   Uses Tailwind CSS for styling
        *   Implements autocomplete functionality
        *   Proper field labeling and validation

**Core Processes:**

1.  **Viewing Inventory:** Users access the root URL (`/inventory/`) to see a table of all items with total inventory value.
2.  **Adding an Item:** Users navigate to `/inventory/add/`, fill out the form with item details, with autocomplete assistance for certain fields.
3.  **Editing an Item:** From the dashboard, users can click an edit button to modify item details at `/inventory/edit/<item_id>/`.
4.  **Deleting an Item:** Users can delete items via an AJAX-powered delete button with confirmation modal.
5.  **Autocomplete:** Type-ahead search functionality for NSN, description, and manufacturer fields to improve data consistency.

The application uses modern web technologies including:
- Tailwind CSS for responsive styling
- AJAX for smooth user interactions
- Autocomplete for improved data entry
- Conditional login protection for secure access
- Modern modal dialogs for confirmations 