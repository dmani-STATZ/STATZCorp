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
- [ ] Create `ProcessContract` model
  - Mirror fields from `Contract` model
  - Add status field to track processing stage
  - Add queue_id field to track source
  - Add created_by and modified_by fields
  - Add timestamps for tracking
  - Add Buyer_text for storeing the Buyer data from the queue table before it gets matched
We shouldn't Need in the ProcessContracts table
status,
open,
date_closed,
cancelled,
date_canceled,
canceled_reason,
survey_date,
survey_type,
assigned_user,
assigned_date,
reviewed,
reviewed_by,
reviewed_on,
notes,


- [ ] Create `ProcessCLIN` model
  - Mirror fields from `CLIN` model
  - Add foreign key to `ProcessContract`
  - Add status field to track processing stage
  - Add timestamps for tracking
  - Add NSN_text for storeing the NSN data from the queue table before it gets matched
  - Add NSN_Description_text for storeing the NSN_Description data from the queue table before it gets matched
  - Add Supplier_text for storeing the Supplier data from the queue table before it gets matched

Fileds we shouldn't need in the ProcessCLIN table
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
- [ ] Create initial migrations for new models
- [ ] Add any necessary indexes
- [ ] Add any necessary constraints

## API Endpoints

### 1. Queue Processing
- [ ] Create endpoint to move contract from queue to processing
  - POST `/procesing/api/start-processing/`
  - Validate queue item exists
  - Create ProcessContract record
  - Create ProcessCLIN records
  - Update queue item status
  - Return success/error

### 2. Processing Management
-  [ ] Create endpoints for processing operations
  - GET `/processing/api/processing/{id}/` - Get processing contract
  - PUT `/processing/api/processing/{id}/` - Update processing contract
  - POST `/processing/api/processing/{id}/clins/` - Add CLIN
  - PUT `/processing/api/processing/{id}/clins/{clin_id}/` - Update CLIN
  - DELETE `/processing/api/processing/{id}/clins/{clin_id}/` - Remove CLIN

### 3. Finalization
- [ ] Create endpoint to finalize processing
  - POST `/processing/api/processing/{id}/finalize/`
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
- [ ] Create `ProcessingContractCreateView`
- [ ] Create `ProcessingContractUpdateView`
- [ ] Create `ProcessingContractDetailView`
- [ ] Create `ProcessingContractListView`

### 2. Templates
- [ ] Create `processing_contract_form.html`
- [ ] Create `processing_contract_detail.html`
- [ ] Create `processing_contract_list.html`
- [ ] Update existing templates to handle processing state

### 3. Forms
- [ ] Create `ProcessingContractForm`
- [ ] Create `ProcessingCLINForm`
- [ ] Create `ProcessingCLINFormSet`

## JavaScript and Frontend

### 1. Processing Page
- [ ] Update contract form to handle processing state
- [ ] Add status indicators
- [ ] Add save draft functionality
- [ ] Add validation for required fields
- [ ] Add CLIN management interface

### 2. Queue Integration
- [ ] Update queue page to handle processing state
- [ ] Add processing status indicators
- [ ] Add ability to resume processing
- [ ] Add ability to cancel processing

## Testing

### 1. Model Tests
- [ ] Test ProcessContract model
- [ ] Test ProcessCLIN model
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