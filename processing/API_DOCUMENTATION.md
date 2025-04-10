# Processing API Documentation

## Overview
This document outlines the API endpoints available for managing contract processing in the system. All endpoints require authentication and return JSON responses.

## Authentication
All endpoints require a valid user session and CSRF token. Include the CSRF token in the `X-CSRFToken` header for non-GET requests.

## Common Response Format
All endpoints follow a consistent response format:

Success Response:
```json
{
    "success": true,
    "message": "Operation successful message",
    "data": { ... }  // Optional data object
}
```

Error Response:
```json
{
    "success": false,
    "error": "Error message or validation errors"
}
```

## Endpoints

### 1. Get Processing Contract
Retrieves the details of a processing contract and its associated CLINs.

**Endpoint:** `GET /processing/api/processing/{id}/`

**Parameters:**
- `id` (path parameter): ID of the processing contract

**Response:**
```json
{
    "success": true,
    "contract": {
        "id": 123,
        "contract_number": "CONTRACT123",
        "solicitation_type": "SDVOSB",
        "po_number": "PO123",
        "tab_num": "TAB1",
        "buyer": 1,  // Buyer ID if matched, null if not
        "buyer_text": "Original buyer text",
        "contract_type": 1,  // Contract type ID
        "award_date": "2024-03-20T00:00:00Z",
        "due_date": "2024-06-20T00:00:00Z",
        "contract_value": 100000.00,
        "description": "Contract description",
        "status": "in_progress"
    },
    "clins": [
        {
            "id": 456,
            "item_number": "0001",
            "nsn": 789,  // NSN ID if matched, null if not
            "nsn_text": "Original NSN text",
            "supplier": 321,  // Supplier ID if matched, null if not
            "supplier_text": "Original supplier text",
            "order_qty": 100,
            "unit_price": 1000.00,
            "item_value": 100000.00,
            "description": "CLIN description"
        }
    ]
}
```

### 2. Update Processing Contract
Updates the details of a processing contract.

**Endpoint:** `PUT /processing/api/processing/{id}/update/`

**Parameters:**
- `id` (path parameter): ID of the processing contract
- Request body: JSON object containing contract fields to update

**Request Body Example:**
```json
{
    "contract_number": "CONTRACT123",
    "solicitation_type": "SDVOSB",
    "po_number": "PO123",
    "tab_num": "TAB1",
    "buyer": 1,
    "buyer_text": "Updated buyer text",
    "contract_type": 1,
    "award_date": "2024-03-20",
    "due_date": "2024-06-20",
    "contract_value": 100000.00,
    "description": "Updated description",
    "status": "ready_for_review"
}
```

**Response:**
```json
{
    "success": true,
    "message": "Contract updated successfully"
}
```

### 3. Add Processing CLIN
Adds a new CLIN to a processing contract.

**Endpoint:** `POST /processing/api/processing/{id}/clins/`

**Parameters:**
- `id` (path parameter): ID of the processing contract
- Request body: JSON object containing CLIN details

**Request Body Example:**
```json
{
    "item_number": "0001",
    "nsn": 789,
    "nsn_text": "NSN description",
    "supplier": 321,
    "supplier_text": "Supplier name",
    "order_qty": 100,
    "unit_price": 1000.00,
    "description": "CLIN description"
}
```

**Response:**
```json
{
    "success": true,
    "clin": {
        "id": 456,
        "item_number": "0001",
        "nsn": 789,
        "nsn_text": "NSN description",
        "supplier": 321,
        "supplier_text": "Supplier name",
        "order_qty": 100,
        "unit_price": 1000.00,
        "item_value": 100000.00,
        "description": "CLIN description"
    }
}
```

### 4. Update Processing CLIN
Updates an existing CLIN in a processing contract.

**Endpoint:** `PUT /processing/api/processing/{id}/clins/{clin_id}/`

**Parameters:**
- `id` (path parameter): ID of the processing contract
- `clin_id` (path parameter): ID of the CLIN to update
- Request body: JSON object containing CLIN fields to update

**Request Body Example:**
```json
{
    "item_number": "0001",
    "nsn": 789,
    "nsn_text": "Updated NSN description",
    "supplier": 321,
    "supplier_text": "Updated supplier name",
    "order_qty": 150,
    "unit_price": 1100.00,
    "description": "Updated CLIN description"
}
```

**Response:**
```json
{
    "success": true,
    "message": "CLIN updated successfully"
}
```

### 5. Delete Processing CLIN
Deletes a CLIN from a processing contract.

**Endpoint:** `DELETE /processing/api/processing/{id}/clins/{clin_id}/delete/`

**Parameters:**
- `id` (path parameter): ID of the processing contract
- `clin_id` (path parameter): ID of the CLIN to delete

**Response:**
```json
{
    "success": true,
    "message": "CLIN deleted successfully"
}
```

## Matching Endpoints

### 1. Match Buyer
Matches or creates a buyer for a processing contract.

**Endpoint:** `POST /processing/match-buyer/{process_contract_id}/`

**Parameters:**
- `process_contract_id` (path parameter): ID of the processing contract
- Request body: JSON object containing buyer details

**Request Body Example:**
```json
{
    "action": "match",  // or "create" for new buyer
    "buyer_id": 123,    // Required if action is "match"
    "buyer_data": {     // Required if action is "create"
        "name": "John Smith",
        "email": "john.smith@example.com",
        "phone": "123-456-7890",
        "organization": "Procurement Office"
    }
}
```

**Response:**
```json
{
    "success": true,
    "buyer": {
        "id": 123,
        "name": "John Smith",
        "email": "john.smith@example.com",
        "phone": "123-456-7890",
        "organization": "Procurement Office"
    },
    "message": "Buyer matched successfully"
}
```

### 2. Match NSN
Matches or creates an NSN (National Stock Number) for a processing CLIN.

**Endpoint:** `POST /processing/match-nsn/{process_clin_id}/`

**Parameters:**
- `process_clin_id` (path parameter): ID of the processing CLIN
- Request body: JSON object containing NSN details

**Request Body Example:**
```json
{
    "action": "match",  // or "create" for new NSN
    "nsn_id": 456,      // Required if action is "match"
    "nsn_data": {       // Required if action is "create"
        "nsn_code": "1234-56-789-0123",
        "description": "Aircraft component",
        "unit_of_measure": "EA",
        "price": 1000.00,
        "notes": "Specific handling required"
    }
}
```

**Response:**
```json
{
    "success": true,
    "nsn": {
        "id": 456,
        "nsn_code": "1234-56-789-0123",
        "description": "Aircraft component",
        "unit_of_measure": "EA",
        "price": 1000.00,
        "notes": "Specific handling required"
    },
    "message": "NSN matched successfully"
}
```

### 3. Match Supplier
Matches or creates a supplier for a processing CLIN.

**Endpoint:** `POST /processing/match-supplier/{process_clin_id}/`

**Parameters:**
- `process_clin_id` (path parameter): ID of the processing CLIN
- Request body: JSON object containing supplier details

**Request Body Example:**
```json
{
    "action": "match",  // or "create" for new supplier
    "supplier_id": 789, // Required if action is "match"
    "supplier_data": {  // Required if action is "create"
        "name": "Aerospace Parts Inc",
        "cage_code": "1A2B3",
        "duns_number": "123456789",
        "address": "123 Industry Lane",
        "city": "Manufacturing City",
        "state": "MC",
        "zip_code": "12345",
        "point_of_contact": "Jane Doe",
        "email": "jane.doe@aerospace.example.com",
        "phone": "987-654-3210"
    }
}
```

**Response:**
```json
{
    "success": true,
    "supplier": {
        "id": 789,
        "name": "Aerospace Parts Inc",
        "cage_code": "1A2B3",
        "duns_number": "123456789",
        "address": "123 Industry Lane",
        "city": "Manufacturing City",
        "state": "MC",
        "zip_code": "12345",
        "point_of_contact": "Jane Doe",
        "email": "jane.doe@aerospace.example.com",
        "phone": "987-654-3210"
    },
    "message": "Supplier matched successfully"
}
```

### Common Error Responses for Matching Endpoints

1. Invalid Action:
```json
{
    "success": false,
    "error": "Invalid action. Must be either 'match' or 'create'"
}
```

2. Missing Required Data:
```json
{
    "success": false,
    "error": "Missing required data for create action"
}
```

3. Entity Not Found:
```json
{
    "success": false,
    "error": "Specified buyer/NSN/supplier not found"
}
```

4. Validation Error:
```json
{
    "success": false,
    "error": {
        "field_name": ["Validation error message"]
    }
}
```

### JavaScript Usage Example for Matching

```javascript
async function matchBuyer(processContractId, buyerData) {
    try {
        const response = await fetch(`/processing/match-buyer/${processContractId}/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify(buyerData)
        });
        
        const result = await response.json();
        if (!result.success) {
            throw new Error(result.error);
        }
        
        return result.buyer;
    } catch (error) {
        console.error('Error matching buyer:', error);
        throw error;
    }
}

// Example usage:
const buyerData = {
    action: 'match',
    buyer_id: 123
};

try {
    const matchedBuyer = await matchBuyer(processContractId, buyerData);
    console.log('Matched buyer:', matchedBuyer);
} catch (error) {
    console.error('Failed to match buyer:', error);
}
```

## Error Handling

### Common Error Responses

1. Authentication Error:
```json
{
    "success": false,
    "error": "Authentication required"
}
```

2. Not Found Error:
```json
{
    "success": false,
    "error": "Process contract not found"
}
```

3. Validation Error:
```json
{
    "success": false,
    "error": {
        "field_name": ["Error message"]
    }
}
```

### HTTP Status Codes

- 200: Successful operation
- 400: Bad request (validation error)
- 401: Unauthorized
- 403: Forbidden
- 404: Not found
- 500: Server error

## Usage Examples

### JavaScript Fetch Example

```javascript
// Update a processing contract
async function updateProcessingContract(id, data) {
    try {
        const response = await fetch(`/processing/api/processing/${id}/update/`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify(data)
        });
        
        const result = await response.json();
        if (!result.success) {
            throw new Error(result.error);
        }
        
        return result;
    } catch (error) {
        console.error('Error updating contract:', error);
        throw error;
    }
}
```

## Notes

1. All date fields should be sent in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ)
2. Numeric fields (contract_value, order_qty, unit_price, item_value) should be sent as numbers, not strings
3. Foreign key fields (buyer, nsn, supplier, contract_type) should be sent as IDs
4. The item_value field for CLINs is calculated automatically from order_qty * unit_price
5. All endpoints require proper CSRF protection for non-GET requests 