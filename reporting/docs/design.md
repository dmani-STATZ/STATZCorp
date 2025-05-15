Here's a breakdown of my thoughts and how you might approach this:

**Core Feasibility:**

* **Selecting Tables/Fields:** Django's ORM (Object-Relational Mapper) makes it possible to dynamically query your database tables and select specific fields. You can build forms or interfaces that allow users to choose which models and fields they want to include in their reports.
* **Adding Criteria/Filters:** Django's querysets provide powerful filtering capabilities. You can translate user-defined criteria (e.g., "where status is 'active'", "where date is within the last month") into Django queryset filters.
* **Sorting:** Django's `order_by()` method on querysets allows you to sort the results based on any field the user selects.
* **Saving Reports:** You can create a Django model to store the configuration of saved reports, including the selected tables/fields, filters, and sorting options.
* **Running Saved Reports:** Retrieving the saved configuration and executing the corresponding database query is straightforward.
* **Exporting to Excel:** Python has excellent libraries like `openpyxl` or `xlsxwriter` that can be used to generate Excel files from your query results. You can create a view that generates the Excel file and serves it as a download.
* **Table View:** Rendering the query results in a simple HTML table is a standard Django template task.

**Challenges and Considerations (Especially Totals/Subtotals):**

* **Dynamic Aggregations (Totals/Subtotals):** This is the most complex part. While Django's aggregation functions (`Sum`, `Count`, etc.) are powerful, applying them dynamically based on user selection can be tricky. You might need to:
    * **Restrict aggregation to specific field types:** It only makes sense to sum or average numerical fields.
    * **Design a user interface for specifying aggregations:** Users would need a way to indicate which fields they want totals or subtotals for and how they want them calculated (sum, average, etc.).
    * **Handle grouping for subtotals:** If a user wants subtotals, they'll likely want to group the data by one or more fields. This adds another layer of complexity to the query and the display logic. You might need to use Django's `annotate()` and `values()` in combination.
* **Security:** Be cautious about allowing users to directly select tables and fields. You'll need to implement security measures to prevent them from accessing sensitive data or constructing malicious queries. You might want to provide a predefined list of available models and fields.
* **Performance:** Dynamically building and executing complex queries based on user input could potentially impact database performance, especially with large datasets. You might need to consider indexing and optimizing your queries.
* **User Interface/User Experience (UI/UX):** Designing an intuitive and user-friendly interface for selecting tables, fields, filters, sorting, and potentially aggregations will be crucial for the success of this feature.

**Potential Approach:**

1.  **Models:**
    * `SavedReport`: Stores the report's name, user who created it, selected model(s), selected fields, filters (potentially as JSON), sorting fields, and possibly aggregation configurations (also potentially as JSON).
2.  **Forms:**
    * Forms to allow users to select models, fields, define filters, and specify sorting. You might need dynamic forms that adapt based on the selected model.
3.  **Views:**
    * A view to display the report creation/editing interface.
    * A view to save new reports and update existing ones.
    * A view to list saved reports.
    * A view to run a saved report:
        * Retrieve the saved configuration.
        * Dynamically construct the Django queryset based on the selected model, fields, filters, and sorting.
        * Handle optional aggregations.
        * Render the data in an HTML table.
    * A view to export the report data to an Excel file using a library like `openpyxl`.

**In summary, building this reporting app is definitely achievable with Django. The core functionalities of selecting data, filtering, sorting, saving, and exporting are well within Django's capabilities. The dynamic totals and subtotals will be the most challenging aspect and will require careful design and implementation.**

Go for it! It sounds like a valuable feature for your users. Start with the basic functionalities and then tackle the more complex aggregation requirements. Let me know if you have more specific questions as you start building.