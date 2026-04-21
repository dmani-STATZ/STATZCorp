\# Technical Design \& Implementation Roadmap



\## 1. Database Schema

\### Model: `TrackerSchema`

\* `name`: (CharField) e.g., "Shipping Workflow".

\* `columns`: (JSONField) Master array of field definitions.

\* `is\_active`: (BooleanField).



\### Model: `ContractRecord`

\* `schema`: (ForeignKey) Link to `TrackerSchema`.

\* `data`: (JSONField) Key-value pairs: `{"c1": "2024-ABC", "c2": "Shipped"}`.

\* `ui\_state`: (JSONField) Meta-info: `{"is\_highlighted": true}`.

\* `status\_sort\_index`: (IntegerField) Denormalized field for high-speed SQL sorting.



\---



\## 2. API Endpoint Requirements



| Method | Endpoint | Purpose |

| :--- | :--- | :--- |

| \*\*GET\*\* | `/api/schema/` | Fetches column definitions for grid rendering. |

| \*\*POST\*\* | `/api/schema/column/` | Appends a new column to the JSON Blueprint. |

| \*\*GET\*\* | `/api/contracts/` | Returns contract list + dynamic data. |

| \*\*PATCH\*\* | `/api/contracts/<id>/` | Toggles highlight or updates a specific cell. |



\---



\## 3. Frontend Component Architecture



\### A. The Column Mapper

\* Maps `TrackerSchema.columns` to grid definitions.

\* \*\*Cell Renderer:\*\* Draws "Pills" for `select` types using the color hex in the JSON.

\* \*\*Editors:\*\* Triggers specific widgets (calendar, checkbox) based on the `type` property.



\### B. The Highlight Engine

\* \*\*Row Class Rules:\*\* Applies `.row-highlighted` CSS class when `ui\_state.is\_highlighted` is true.

\* \*\*CSS:\*\* `.row-highlighted { background-color: #FFF9C4 !important; }`.



\---



\## 4. Business Logic Implementation



\### Logical Sort Handler

1\. Detect sort request on a "Select" column.

2\. Reference the Blueprint to find the `sort\_priority` for the current cell value.

3\. Perform the sort based on the priority integer.



\### Search \& Scroll Script

1\. User enters text in the "Quick Search" input.

2\. Grid API identifies the row index of the first match.

3\. Call `gridApi.ensureIndexVisible(index, 'top')` to jump the browser to that record.



\---



\## 5. Development Roadmap



\* \*\*Phase 1 (Backend):\*\* Define models, write "Schema Update" service, and create initial DRF/Ninja views.

\* \*\*Phase 2 (Frontend):\*\* Integrate Datagrid (AG Grid/Tabulator), build the Dynamic Column Generator, and create the "Field Settings" modal.

\* \*\*Phase 3 (Polish):\*\* Add highlighter icons, test color rendering, and optimize MS SQL JSON query performance.

