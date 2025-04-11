# Contract Split Implementation Guide

## Overview
This document details the implementation of dynamic contract splits in the Django application. The system allows for flexible allocation of contract proceeds between multiple companies, replacing the previous static STATZ/PPI split system.

## Database Schema

### ContractSplit Model
```python
class ContractSplit(models.Model):
    process_contract = models.ForeignKey(ProcessContract, on_delete=models.CASCADE, related_name='splits')
    company_name = models.CharField(max_length=100)
    split_value = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    split_paid = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['company_name']
        verbose_name = 'Contract Split'
        verbose_name_plural = 'Contract Splits'
```

### Key Fields
- `process_contract`: Links the split to a specific contract
- `company_name`: Name of the company receiving the split
- `split_value`: The allocated amount for this company
- `split_paid`: The amount already paid to this company
- `created_at/modified_at`: Timestamps for tracking changes

## Form Implementation

### ContractSplitForm
```python
class ContractSplitForm(forms.ModelForm):
    class Meta:
        model = ContractSplit
        fields = ['company_name', 'split_value', 'split_paid']
```

### ProcessContractForm Extensions
The main form handling the contract includes custom methods for managing splits:

1. **Initialization**:
```python
def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.splits_data = []
    
    if self.data:
        # Extract splits data from POST
        for key in self.data:
            if key.startswith('splits-'):
                parts = key.split('-')
                if len(parts) == 3:  # splits-[id/new]-[field]
                    split_id = parts[1]
                    field = parts[2]
                    split_data = self._get_or_create_split_data(split_id)
                    split_data[field] = self.data[key]
```

2. **Save Method**:
```python
def save(self, commit=True):
    instance = super().save(commit=False)
    
    if commit:
        instance.save()
        self._handle_splits(instance)
    
    return instance
```

## Template Implementation

### Split Management Interface
```html
<div class="bg-white rounded-lg shadow-md p-6 mb-6">
    <!-- Header with Add Button -->
    <div class="flex justify-between items-center mb-4">
        <h2 class="text-xl font-semibold">Splits Information</h2>
        <button type="button" 
                onclick="addNewSplit()"
                class="px-4 py-2 bg-green-500 text-white rounded-md">
            Add New Split
        </button>
    </div>
    
    <!-- Dynamic Splits Table -->
    <table class="min-w-full" id="splitsTable">
        <thead>
            <tr>
                <th>Company</th>
                <th>Split Value</th>
                <th>Split Paid</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody>
            {% for split in process_contract.splits.all %}
            <!-- Split rows here -->
            {% endfor %}
        </tbody>
    </table>
</div>
```

## JavaScript Functions

### Adding New Splits
```javascript
function addNewSplit() {
    const table = document.querySelector('#splitsTable tbody');
    const timestamp = new Date().getTime();
    const newRow = createSplitRow(timestamp);
    table.appendChild(newRow);
    updateTotalSplitValue();
}
```

### Removing Splits
```javascript
function removeSplit(button) {
    const row = button.closest('tr');
    row.remove();
    updateTotalSplitValue();
}
```

### Updating Totals
```javascript
function updateTotalSplitValue() {
    const splitValues = document.querySelectorAll('input[name$="-value"]');
    let total = 0;
    splitValues.forEach(input => {
        total += parseFloat(input.value || 0);
    });
    document.getElementById('totalSplitValue').textContent = total.toFixed(2);
}
```

## Migration Strategy

### From Static to Dynamic Splits
1. Create new ContractSplit model
2. Remove old split fields from ProcessContract
3. Create data migration to convert existing splits
4. Update forms and templates
5. Test data integrity

```python
# Example Data Migration
def migrate_existing_splits(apps, schema_editor):
    ProcessContract = apps.get_model('processing', 'ProcessContract')
    ContractSplit = apps.get_model('processing', 'ContractSplit')
    
    for contract in ProcessContract.objects.all():
        # Migrate PPI split
        if contract.ppi_split:
            ContractSplit.objects.create(
                process_contract=contract,
                company_name='PPI',
                split_value=contract.ppi_split,
                split_paid=contract.ppi_split_paid
            )
        
        # Migrate STATZ split
        if contract.statz_split:
            ContractSplit.objects.create(
                process_contract=contract,
                company_name='STATZ',
                split_value=contract.statz_split,
                split_paid=contract.statz_split_paid
            )
```

## Validation Rules

1. **Total Split Validation**
   - Total of all splits should not exceed contract value
   - Implement in form clean method
   - Add JavaScript validation

2. **Paid Amount Validation**
   - Split paid should not exceed split value
   - Implement in model clean method

## Future Implementation in Contracts App

### Steps for Contracts App Implementation

1. **Create ContractSplit Model**
```python
class ContractSplit(models.Model):
    contract = models.ForeignKey('Contract', on_delete=models.CASCADE, related_name='splits')
    company_name = models.CharField(max_length=100)
    split_value = models.DecimalField(max_digits=19, decimal_places=4)
    split_paid = models.DecimalField(max_digits=19, decimal_places=4, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
```

2. **Modify Contract Model**
   - Remove existing split fields
   - Add reverse relationship to splits

3. **Update Forms**
   - Copy ProcessContractForm split handling
   - Adapt for Contract model

4. **Update Templates**
   - Copy split management interface
   - Adapt for Contract context

5. **Data Migration**
   - Create migration for new model
   - Convert existing static splits
   - Validate data integrity

### Processing to Contract Transfer

When finalizing a ProcessContract to Contract:

```python
def transfer_splits(process_contract, final_contract):
    for process_split in process_contract.splits.all():
        ContractSplit.objects.create(
            contract=final_contract,
            company_name=process_split.company_name,
            split_value=process_split.split_value,
            split_paid=process_split.split_paid
        )
```

## Best Practices

1. **Data Integrity**
   - Always validate total splits against contract value
   - Ensure paid amounts don't exceed split values
   - Maintain audit trail of changes

2. **User Interface**
   - Provide clear feedback on validation errors
   - Show running totals and remaining amounts
   - Enable easy addition/removal of splits

3. **Performance**
   - Use select_related for efficient querying
   - Batch create/update operations
   - Index frequently queried fields

4. **Security**
   - Validate all input data
   - Implement proper permissions
   - Log significant changes

## Testing Strategy

1. **Model Tests**
   - Test split creation/modification
   - Validate constraints
   - Test edge cases

2. **Form Tests**
   - Test split data handling
   - Validate form cleaning
   - Test validation rules

3. **View Tests**
   - Test CRUD operations
   - Test permissions
   - Test error handling

4. **Integration Tests**
   - Test complete workflow
   - Test data migration
   - Test edge cases

## Maintenance Considerations

1. **Monitoring**
   - Track split operations
   - Monitor data integrity
   - Alert on validation failures

2. **Backup Strategy**
   - Regular backups
   - Version control
   - Audit trail

3. **Performance Optimization**
   - Index key fields
   - Optimize queries
   - Cache where appropriate 