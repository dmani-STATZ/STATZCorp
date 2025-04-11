# Contract Processing Workflow Implementation

## Overview
This document outlines the steps needed to implement a new contract processing workflow that uses separate processing tables to handle contract creation before moving them to the live system.

- Starting at the Contract Queue @processing/templates/processing/contract_queue.html
- Processing in a Contract Creation Form/Template
    - Allowing for saveing to the user can leave a return to the contract.
    - Funtions for the user to Match Buyer, NSN, Supplier to a live record or create a new record
- Save the Contract and CLINs to the live table

## Database Changes

### 1. New Models
- [x] Create `ProcessContract` model ✓
  - Mirror fields from `Contract` model
  - Add status field to track processing stage
  - Add queue_id field to track source
  - Add created_by and modified_by fields
  - Add timestamps for tracking
  - Add Buyer_text for storing the Buyer data from the queue table before it gets matched

- [x] Create `ProcessClin` model ✓
  - Mirror fields from `Clin` model
  - Add foreign key to `ProcessContract`
  - Add status field to track processing stage
  - Add timestamps for tracking
  - Add NSN_text for storing the NSN data from the queue table before it gets matched
  - Add NSN_Description_text for storing the NSN_Description data from the queue table before it gets matched
  - Add Supplier_text for storing the Supplier data from the queue table before it gets matched

Fileds we shouldn't need in the ProcessClin table
ship_qty,
ship_date,
ship_date_late,
notes,
paid_amount,
paid_date,
wawf_payment,
wawf_recieved,
wawf_invoice,

### 2. Migrations
- [x] Create initial migrations for new models ✓
- [x] Add any necessary indexes ✓
- [x] Add any necessary constraints ✓

## API Endpoints

### 1. Queue Processing
- [x] Create endpoint to move contract from queue to processing ✓
  - POST `/processing/start-processing/<queue_id>/` (Implemented)
  - Validate queue item exists
  - Create ProcessContract record
  - Create ProcessClin records
  - Update queue item status
  - Return success/error

### 2. Processing Management
- [x] Create endpoints for processing operations ✓
  - GET `/processing/api/processing/{id}/` - Get processing contract
  - PUT `/processing/api/processing/{id}/` - Update processing contract
  - POST `/processing/api/processing/{id}/clins/` - Add CLIN
  - PUT `/processing/api/processing/{id}/clins/{clin_id}/` - Update CLIN
  - DELETE `/processing/api/processing/{id}/clins/{clin_id}/` - Remove CLIN

### 3. Finalization
- [x] Create endpoint to finalize processing ✓
  - POST `/processing/contract/<process_contract_id>/finalize/` (Implemented)
  - Validate all required fields
  - Create Contract record
  - Create CLIN records
  - Delete processing records
  - Update queue status
  - Return success/error

## Views and Templates

## Keys to take into account.
- Queue field Buyer in the Contracts section needs to populate the buyer_text field and have ways to match it to the live Buyer table or Add to the Buyer table and return the id created
- Queue field NSNS in the CLIN section needs to populate the nsn_text fields and have a way to match to the live nsn table or add to the nsn table and return the id created
- Queue field Supplier in the CLIN section needs to populate the supplier_text field and have a way to match to the live supplier table or add to the supplier table and return the id created

### 1. Processing Views
- [x] Create `ProcessingContractCreateView` (Implemented as part of start_processing)
- [x] Create `ProcessingContractUpdateView` ✓
- [x] Create `ProcessingContractDetailView` ✓
- [x] Create `ProcessingContractListView` (Implemented as ContractQueueListView)

### 2. Templates
- [x] Create `processing_contract_form.html` ✓
- [x] Create `processing_contract_detail.html` ✓
- [ ] Create `processing_contract_list.html` (Using contract_queue.html instead)
- [x] Update existing templates to handle processing state ✓

### 3. Forms
- [x] Create `ProcessingContractForm` ✓
- [x] Create `ProcessingCLINForm` ✓
- [x] Create `ProcessingCLINFormSet` ✓

## JavaScript and Frontend

### 1. Processing Page
- [x] Update contract form to handle processing state ✓
- [x] Add status indicators ✓
- [x] Add save draft functionality ✓
- [x] Add validation for required fields ✓
- [x] Add CLIN management interface ✓

### 2. Queue Integration
- [x] Update queue page to handle processing state ✓
- [x] Add processing status indicators ✓
- [x] Add ability to resume processing ✓
- [x] Add ability to cancel processing ✓ (Implemented with confirmation dialogs in both queue and processing views)

## Testing

### 1. Model Tests
- [ ] Test ProcessContract model
- [ ] Test ProcessClin model
- [ ] Test model relationships
- [ ] Test model methods

### 2. View Tests
- [ ] Test processing views
- [ ] Test form handling
- [ ] Test validation
- [ ] Test error handling

### 3. API Tests
- [ ] Test processing endpoints
- [ ] Test queue integration
- [ ] Test finalization process
- [ ] Test error cases

### 4. Integration Tests
- [ ] Test full workflow
- [ ] Test concurrent processing
- [ ] Test data integrity
- [ ] Test error recovery

## Documentation

### 1. Code Documentation
- [ ] Document models
- [ ] Document views
- [ ] Document forms
- [ ] Document API endpoints

### 2. User Documentation
- [ ] Document processing workflow
- [ ] Document user interface
- [ ] Document error handling
- [ ] Document best practices

## Deployment

### 1. Database Updates
- [ ] Plan migration strategy
- [ ] Create rollback plan
- [ ] Test migrations
- [ ] Document deployment steps

### 2. Code Deployment
- [ ] Update requirements
- [ ] Update settings
- [ ] Test in staging
- [ ] Plan production deployment

## Monitoring and Maintenance

### 1. Logging
- [ ] Add processing logs
- [ ] Add error tracking
- [ ] Add performance metrics
- [ ] Add audit trails

### 2. Cleanup
- [ ] Add cleanup job for abandoned processing
- [ ] Add cleanup job for old queue items
- [ ] Add monitoring for processing timeouts
- [ ] Add alerts for processing issues

## Future Enhancements

### 1. Features
- [ ] Add batch processing
- [ ] Add template support
- [ ] Add validation rules
- [ ] Add approval workflow

### 2. Performance
- [ ] Add caching
- [ ] Add async processing
- [ ] Add bulk operations
- [ ] Add optimization

## Notes
- Keep processing tables separate from live tables
- Ensure data integrity during transitions
- Handle concurrent processing
- Provide clear user feedback
- Maintain audit trail
- Support rollback if needed 