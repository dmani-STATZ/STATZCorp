## Inventory Application Process Write-up

**Objective:** The `inventory` application manages warehouse inventory items, providing functionalities for adding, viewing, updating, and deleting stock records.

**Key Components:**

1.  **Model (`InventoryItem`):**
    *   Located in `inventory/models.py`.
    *   Represents a single inventory item in the `STATZ_WAREHOUSE_INVENTORY_TBL` database table.
    *   Fields: `nsn`, `description`, `partnumber`, `manufacturer`, `itemlocation`, `quantity`, `purchaseprice`.
    *   Calculated Field: `totalcost` (automatically calculated as `purchaseprice * quantity` upon saving).

2.  **Form (`InventoryItemForm`):**
    *   Located in `inventory/forms.py`.
    *   A `ModelForm` based on the `InventoryItem` model.
    *   Excludes `id` and `totalcost` fields from user input.
    *   Uses `crispy_forms` for structured layout and styling.
    *   Includes CSS classes for potential autocomplete functionality on `nsn`, `description`, and `manufacturer` fields.

3.  **Views (`inventory/views.py`):**
    *   `inventory_list_view`:
        *   Displays a list of all inventory items.
        *   Retrieves all `InventoryItem` objects.
        *   Uses `django_tables2` (`InventoryTable`) to render the data in a sortable, paginated table.
        *   Context includes the table object.
        *   Renders `inventory/inventory_list.html`.
    *   `inventory_add_view`:
        *   Handles the creation of new inventory items.
        *   If `GET`, displays an empty `InventoryItemForm`.
        *   If `POST`, validates the submitted `InventoryItemForm`.
        *   If valid, saves the new `InventoryItem` and redirects to the `inventory_list_view`.
        *   If invalid, re-renders the form with errors.
        *   Renders `inventory/inventory_form.html`.
    *   `inventory_edit_view`:
        *   Handles updating an existing inventory item identified by `pk` (primary key).
        *   Retrieves the specific `InventoryItem` instance.
        *   If `GET`, displays the `InventoryItemForm` pre-filled with the item's data.
        *   If `POST`, validates the submitted `InventoryItemForm` bound to the instance.
        *   If valid, saves the updated `InventoryItem` and redirects to the `inventory_list_view`.
        *   If invalid, re-renders the form with errors.
        *   Renders `inventory/inventory_form.html`.
    *   `inventory_delete_view`:
        *   Handles the deletion of an existing inventory item identified by `pk`.
        *   Retrieves the specific `InventoryItem` instance.
        *   If `GET`, displays a confirmation page (`inventory/inventory_confirm_delete.html`).
        *   If `POST`, deletes the `InventoryItem` and redirects to the `inventory_list_view`.
    *   `inventory_bulk_add_view`:
        *   Provides a form (`BulkInventoryAddForm`) to add multiple items at once via CSV upload or direct text input.
        *   If `POST`, processes the input data (CSV or text).
        *   Parses each row, creates `InventoryItem` instances, and performs a bulk create operation for efficiency.
        *   Redirects to `inventory_list_view` after processing.
        *   Renders `inventory/inventory_bulk_add.html`.
    *   `inventory_export_view`:
        *   Exports the current inventory list to a CSV file.
        *   Retrieves all `InventoryItem` objects.
        *   Creates an HTTP response with CSV content type and appropriate headers for download.
        *   Uses Python's `csv` module to write the data.

4.  **URLs (`inventory/urls.py`):**
    *   Defines URL patterns mapping paths to the corresponding views:
        *   `/`: `inventory_list_view` (name: `inventory_list`)
        *   `/add/`: `inventory_add_view` (name: `inventory_add`)
        *   `/edit/<int:pk>/`: `inventory_edit_view` (name: `inventory_edit`)
        *   `/delete/<int:pk>/`: `inventory_delete_view` (name: `inventory_delete`)
        *   `/bulk-add/`: `inventory_bulk_add_view` (name: `inventory_bulk_add`)
        *   `/export/`: `inventory_export_view` (name: `inventory_export`)

5.  **Templates (`inventory/templates/inventory/`):**
    *   `inventory_list.html`: Displays the table of inventory items using `django_tables2`. Includes links/buttons for adding, editing, deleting, bulk adding, and exporting.
    *   `inventory_form.html`: Renders the `InventoryItemForm` using `crispy_forms` for adding or editing items.
    *   `inventory_confirm_delete.html`: Confirmation page for deleting an item.
    *   `inventory_bulk_add.html`: Renders the `BulkInventoryAddForm` for bulk uploads.

**Core Processes:**

1.  **Viewing Inventory:** Users access the root URL (`/inventory/`) to see a paginated and sortable list of all items in the warehouse.
2.  **Adding a Single Item:** Users navigate to `/inventory/add/`, fill out the form with item details (NSN, description, part number, etc.), and submit. The system validates the data, calculates the total cost, saves the new item, and redirects back to the inventory list.
3.  **Editing an Item:** From the inventory list, users can click an edit link/button associated with an item. This takes them to `/inventory/edit/<item_id>/`, where the item's details are pre-filled in the form. Users modify the details, submit, and upon validation, the item is updated, and they are redirected to the list.
4.  **Deleting an Item:** Users click a delete link/button, leading to `/inventory/delete/<item_id>/`. They are presented with a confirmation page. Upon confirming (via a POST request), the item is removed from the database, and the user is redirected to the list.
5.  **Bulk Adding Items:** Users navigate to `/inventory/bulk-add/`. They can either upload a CSV file or paste data directly into a text area, following a specific format. The system parses this data, creates multiple `InventoryItem` objects in a single database transaction, and redirects to the inventory list.
6.  **Exporting Inventory:** Users click an export button (likely on the list view), triggering a request to `/inventory/export/`. The system generates a CSV file containing all current inventory items and prompts the user to download it.

This structure follows standard Django MVT patterns, utilizing class-based and function-based views, ModelForms for data handling, and `django_tables2` for presentation. It leverages Django's ORM for database interaction and includes features for both single-item and bulk operations. 