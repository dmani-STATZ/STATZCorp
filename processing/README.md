## Processing Application Process Write-up

**Objective:** The `processing` application serves as a staging area and workflow manager for ingesting, validating, matching, and finalizing new contract and CLIN data before it becomes active in the main `contracts` application.

**Key Components:**

1.  **Models (`processing/models.py`):
    *   **Queue Models (`QueueContract`, `QueueClin`):** Store raw contract/CLIN data as it arrives (e.g., from CSV upload). Related entities (buyer, NSN, supplier) are stored as text strings initially.
    *   **Processing Models (`ProcessContract`, `ProcessClin`, `ProcessContractSplit`):** Represent a contract actively being worked on. They mirror the main `contracts` models but include both text fields (from the queue) and ForeignKeys (for matched entities). Track processing status (`draft`, `in_progress`, `ready_for_review`, `completed`). Link back to the queue item and forward to the final `contracts` record upon completion.
    *   **Utility Model (`SequenceNumber`):** Manages auto-incrementing PO and Tab numbers, ensuring uniqueness.

2.  **Forms (`processing/forms.py`):
    *   `ProcessContractForm`: Edits the main processing contract details, including text and matched fields. Handles saving associated `ProcessContractSplit` data.
    *   `ProcessClinForm`: Edits processing CLIN details. Includes logic to auto-calculate values.
    *   `ProcessClinFormSet`: An inline formset to manage multiple `ProcessClin` records associated with a `ProcessContract`.
    *   `ContractSplitForm`: Basic form for `ProcessContractSplit`.

3.  **Views (Modular Structure in `processing/views/`):
    *   `processing_views.py`: Handles the core workflow - viewing the queue (`ContractQueueListView`), initiating processing (`initiate_processing`, `start_processing`), the main editing interface (`ProcessContractUpdateView`), finalizing (`finalize_contract`), CSV upload/download.
    *   `matching_views.py`: Contains views/logic dedicated to matching string data (e.g., buyer name, NSN code) from processing records to existing `contracts` models (`match_buyer`, `match_nsn`, `match_supplier`, `match_idiq`).
    *   `api_views.py`: Provides AJAX endpoints for dynamic updates within the processing interface (e.g., getting/updating data, adding/deleting CLINs).

4.  **URLs (`processing/urls.py`):
    *   Maps URLs for queue management (`/queue/`, `/start-new-contract/`).
    *   Defines URLs for the contract processing interface (`/contract/<pk>/edit/`).
    *   Includes URLs for specific actions like starting processing (`/start-processing/<queue_id>/`), finalizing (`/contract/.../finalize/`), saving progress (`/save-contract-data/...`), and canceling.
    *   Provides endpoints for the matching logic (`/match-buyer/...`, etc.).
    *   Maps API endpoints (`/api/...`).
    *   Includes URLs for CSV template download and upload (`/download-template/`, `/upload/`).

5.  **Templates (`processing/templates/processing/`):
    *   Contains HTML templates for the queue view, the main contract processing interface (likely using the formset), matching modals/interfaces, and upload forms.

**Core Processes:**

1.  **Ingestion (Queueing):**
    *   New contract data (potentially from external sources) is loaded into `QueueContract` and `QueueClin` records, often via CSV upload (`/upload/`).
2.  **Processing Initiation:**
    *   Users view the pending items in the queue (`/queue/`).
    *   A user selects an item from the queue and initiates processing (`/start-processing/<queue_id>/`). This likely creates corresponding `ProcessContract`, `ProcessClin`, and `ProcessContractSplit` records, marks the queue item as `is_being_processed`, and assigns PO/Tab numbers using `SequenceNumber`.
    *   Alternatively, users might start a new, blank processing contract (`/start-new-contract/`).
3.  **Interactive Processing & Matching:**
    *   Users interact with the main processing view (`/contract/<pk>/edit/`).
    *   This view displays `ProcessContractForm` and `ProcessClinFormSet`.
    *   Users validate and refine the data.
    *   Crucially, they use matching tools/views (triggered by `/match-.../` URLs) to link text fields (like `buyer_text`, `nsn_text`) to actual records in the `contracts` app. These tools might search the `contracts` models and allow selecting an existing record or creating a new one.
    *   Matched ForeignKeys (`buyer`, `nsn`, etc.) in `ProcessContract`/`ProcessClin` are populated.
    *   Contract splits can be managed (`/contract/split/...`).
    *   Progress can be saved (`/save-contract-data/...`) without finalizing.
4.  **Review & Finalization:**
    *   Once processing is complete, the contract is marked for review (`/process-contract/.../mark-ready/`).
    *   After review (potentially by another user), the contract is finalized (`/contract/.../finalize/`).
    *   Finalization involves:
        *   Creating the definitive `Contract`, `Clin`, and `ContractSplit` records in the `contracts` application based on the data in `ProcessContract`/`ProcessClin`/`ProcessContractSplit`.
        *   Linking the `ProcessContract`/`ProcessClin` to the newly created final records (`final_contract`, `final_clin`).
        *   Updating the status of the `ProcessContract` to 'completed'.
        *   (Optionally) Deleting or archiving the original `QueueContract`/`QueueClin` item.
5.  **Cancellation:**
    *   Processing can be canceled at the queue stage (`/queue/cancel/...`) or during active processing (`/process-contract/cancel/...`), updating the status accordingly.

This application streamlines the creation of new contracts by providing a controlled environment for data entry, validation, matching against existing records, and final review before committing the data to the main `contracts` system. 