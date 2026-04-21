\# Specification Sheet: Dynamic Contract Tracking Module (DCTM)



\## 1. Project Overview

\* \*\*Purpose:\*\* To replace legacy folder-tracking software with a dynamic, browser-based grid.

\* \*\*Core Goal:\*\* Enable users to define their own tracking columns, workflow steps, and visual statuses without developer intervention.

\* \*\*Host Environment:\*\* Existing Django Project (MS SQL Server / PostgreSQL compatible).



\---



\## 2. Data Architecture

The system utilizes a \*\*Two-Part JSON Blueprint\*\* strategy to allow dynamic column creation without database migrations.



\### A. The Blueprint (Metadata)

Stored in a `TrackerSchema` model. Defines the "Columns" of the spreadsheet.

\* \*\*Field ID:\*\* Unique key (e.g., `col\_823`) to prevent data loss if a label is renamed.

\* \*\*Label:\*\* Display name (e.g., "Shipping Status").

\* \*\*Type:\*\* `text`, `date`, `checkbox`, or `select`.

\* \*\*Options:\*\* (For `select` types) A list of objects containing `value`, `color\_hex`, and `sort\_priority`.

\* \*\*Order:\*\* Integer to manage left-to-right column positioning.



\### B. The Record (Data)

Stored in a `ContractRecord` model. 

\* \*\*Data Blob:\*\* A JSON object mapping Field IDs to values: `{"col\_823": "Shipped", "col\_101": "2026-05-12"}`.

\* \*\*Meta Blob:\*\* Stores UI states like `is\_highlighted: true`.



\---



\## 3. Functional Requirements



\### Column \& Field Management

\* \*\*Dynamic Addition:\*\* Users can add new columns via the UI.

\* \*\*Field Types Supported:\*\* \* \*\*Text:\*\* Standard alphanumeric input.

&#x20;   \* \*\*Date:\*\* Interactive calendar picker.

&#x20;   \* \*\*Checkbox:\*\* Boolean toggle for "Yes/No" states.

&#x20;   \* \*\*Select (Status):\*\* Dropdown where each option is assigned a unique background color (Status Pill).



\### Visual Interaction

\* \*\*Row Highlighting:\*\* A "Highlighter" toggle on each row. When active, the entire row background changes to a specific attention color (e.g., Light Yellow).

\* \*\*Status Pills:\*\* Selection fields render with user-defined background colors for immediate visual recognition.



\### Navigation \& Organization

\* \*\*Logical Sorting:\*\* Sorting by "Status" follows user-defined `sort\_priority` (chronological) rather than alphabetical order.

\* \*\*Search \& Jump:\*\* A global search bar that automatically scrolls to and highlights the matching row, overcoming DOM virtualization limits.



\---



\## 4. Security \& Integrity

\* \*\*Data Validation:\*\* Backend must validate JSON inputs against the Blueprint (e.g., verifying date formats).

\* \*\*Audit Trail:\*\* (Optional) Tracking of status changes and highlight toggles.

