// Initialize variables
let availableModels = {};
let currentSort = null;
let fieldSearchTimeout = null;

console.log('Report creation script loading...');

document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM Content Loaded');
    
    // Get DOM elements
    const availableTables = document.getElementById('availableTables');
    const selectedTables = document.getElementById('selectedTables');
    const availableFields = document.getElementById('availableFields');
    const selectedFields = document.getElementById('selectedFields');
    const addTableBtn = document.getElementById('addTable');
    const removeTableBtn = document.getElementById('removeTable');
    const addFieldBtn = document.getElementById('addField');
    const removeFieldBtn = document.getElementById('removeField');
    const fieldSearch = document.getElementById('fieldSearch');
    const fieldsLoading = document.getElementById('fieldsLoading');
    const selectedTablesInput = document.getElementById('id_selected_tables');
    const selectedFieldsInput = document.getElementById('id_selected_fields');
    const messagesDiv = document.getElementById('messages');
    const messagesContent = messagesDiv.querySelector('div');

    console.log('Elements found:', {
        availableTables: !!availableTables,
        selectedTables: !!selectedTables,
        addTableBtn: !!addTableBtn,
        removeTableBtn: !!removeTableBtn,
        selectedTablesInput: !!selectedTablesInput,
        selectedFieldsInput: !!selectedFieldsInput,
        filterField: !!filterField,
        sortField: !!sortField
    });

    // Log initial state
    if (availableTables) {
        console.log('Available tables options:', Array.from(availableTables.options).map(opt => opt.value));
    }
    if (selectedTables) {
        console.log('Selected tables options:', Array.from(selectedTables.options).map(opt => opt.value));
    }

    // Initialize filter and sort fields if we have initial data
    if (window.initialData) {
        console.log('Initializing with data:', window.initialData);
        // First update available fields which will trigger filter and sort updates
        updateAvailableFields();
    } else {
        // Just initialize empty filter and sort fields
        updateFilterFields();
        updateSortFields();
    }

    // Function to show loading state
    function showFieldsLoading(show) {
        fieldsLoading.classList.toggle('hidden', !show);
        addFieldBtn.disabled = show;
        removeFieldBtn.disabled = show;
    }

    // Function to filter available fields
    function filterFields(searchTerm) {
        const options = availableFields.options;
        const term = searchTerm.toLowerCase();
        
        for (let option of options) {
            const text = option.text.toLowerCase();
            const value = option.value.toLowerCase();
            const matches = text.includes(term) || value.includes(term);
            option.style.display = matches ? '' : 'none';
        }
    }

    // Add field search functionality with debounce
    fieldSearch.addEventListener('input', function(e) {
        if (fieldSearchTimeout) {
            clearTimeout(fieldSearchTimeout);
        }
        fieldSearchTimeout = setTimeout(() => {
            filterFields(e.target.value);
        }, 200);
    });

    // Helper function to move selected options between select elements
    function moveSelectedOptions(fromSelect, toSelect) {
        console.log('Moving options from', fromSelect.id, 'to', toSelect.id);
        console.log('Selected options:', Array.from(fromSelect.selectedOptions).map(opt => opt.value));
        
        const selectedValues = Array.from(fromSelect.selectedOptions).map(opt => opt.value);
        if (selectedValues.length === 0) {
            console.log('No options selected');
            showMessage('Please select items to move', 'error');
            return false;
        }
        selectedValues.forEach(val => {
            const option = Array.from(fromSelect.options).find(opt => opt.value === val);
            if (option) {
                console.log('Moving option:', option.value);
                const newOption = option.cloneNode(true);
                toSelect.appendChild(newOption);
                fromSelect.removeChild(option);
            }
        });
        return true;
    }

    // Show message in the messages area
    function showMessage(message, type) {
        messagesDiv.classList.remove('hidden');
        messagesContent.textContent = message;
        messagesContent.className = type === 'error' 
            ? 'bg-red-100 border-l-4 border-red-500 text-red-700 p-4'
            : 'bg-blue-100 border-l-4 border-blue-500 text-blue-700 p-4';
    }

    // Update available fields based on selected tables
    function updateAvailableFields() {
        const selectedTablesList = Array.from(selectedTables.options).map(opt => opt.value);
        selectedTablesInput.value = JSON.stringify(selectedTablesList);
        
        // Clear field search when updating fields
        fieldSearch.value = '';
        
        if (selectedTablesList.length === 0) {
            availableFields.innerHTML = '';
            availableModels = {};
            updateFilterFields();
            updateSortFields();
            updateAggregationFields();
            return Promise.resolve(); // Return a resolved promise for consistency
        }
        
        showFieldsLoading(true);
        return fetch(`/reporting/api/get-model-fields/?selected_tables=${encodeURIComponent(JSON.stringify(selectedTablesList))}`)
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    showMessage(data.error, 'error');
                    return;
                }
                
                // Store field information
                availableModels = data.fields;
                
                // Clear existing options
                availableFields.innerHTML = '';
                
                // Add new options with tooltips, grouped by table
                selectedTablesList.forEach(tableName => {
                    const tableFields = data.fields[tableName];
                    if (tableFields && tableFields.length > 0) {
                        // Add table group
                        const groupLabel = document.createElement('optgroup');
                        groupLabel.label = tableName.charAt(0).toUpperCase() + tableName.slice(1);
                        availableFields.appendChild(groupLabel);
                        
                        // Add fields for this table
                        tableFields.forEach(field => {
                            const option = document.createElement('option');
                            option.value = `${tableName}.${field.name}`;
                            option.textContent = field.verbose_name;
                            option.title = `Type: ${field.type}\n${field.verbose_name}`;
                            groupLabel.appendChild(option);
                        });
                    }
                });
                
                // Show message if linking tables were added
                if (data.message) {
                    showMessage(data.message, 'info');
                }
                
                // Update filter and sort fields
                updateFilterFields();
                updateSortFields();
                updateAggregationFields();
            })
            .catch(error => {
                console.error('Error fetching fields:', error);
                showMessage('Error loading fields. Please try again.', 'error');
            })
            .finally(() => {
                showFieldsLoading(false);
            });
    }

    // Function to update filter fields
    function updateFilterFields() {
        console.log('Updating filter fields');
        filterField.innerHTML = '<option value="">Select a field...</option>';
        
        // Add all available fields to the filter dropdown
        const allFields = new Set();
        
        // Add from available fields
        Array.from(availableFields.options).forEach(opt => {
            if (!allFields.has(opt.value)) {
                const option = document.createElement('option');
                option.value = opt.value;
                option.textContent = opt.textContent;
                filterField.appendChild(option);
                allFields.add(opt.value);
            }
        });
        
        // Add from selected fields
        Array.from(selectedFields.options).forEach(opt => {
            if (!allFields.has(opt.value)) {
                const option = document.createElement('option');
                option.value = opt.value;
                option.textContent = opt.textContent;
                filterField.appendChild(option);
                allFields.add(opt.value);
            }
        });
        
        // Clear any existing filter values
        clearFilterBuilder();
        
        // If in edit mode and there are filters to restore
        if (window.initialData && window.initialData.filters) {
            filters = window.initialData.filters;
            renderFilters();
        }
    }

    // Add table button click handler with more logging
    addTableBtn.addEventListener('click', function() {
        console.log('Add table button clicked');
        console.log('Available tables before:', Array.from(availableTables.options).map(opt => opt.value));
        console.log('Selected tables before:', Array.from(selectedTables.options).map(opt => opt.value));
        
        if (moveSelectedOptions(availableTables, selectedTables)) {
            console.log('Options moved successfully');
            console.log('Available tables after:', Array.from(availableTables.options).map(opt => opt.value));
            console.log('Selected tables after:', Array.from(selectedTables.options).map(opt => opt.value));
            updateAvailableFields();
        } else {
            console.log('Failed to move options');
        }
    });

    // Remove table button click handler
    removeTableBtn.addEventListener('click', function() {
        console.log('Remove table button clicked');
        console.log('Available tables before:', Array.from(availableTables.options).map(opt => opt.value));
        console.log('Selected tables before:', Array.from(selectedTables.options).map(opt => opt.value));
        
        if (moveSelectedOptions(selectedTables, availableTables)) {
            // Get the removed tables
            const removedTables = Array.from(availableTables.options)
                .filter(opt => opt.selected)
                .map(opt => opt.value);
                
            console.log('Removed tables:', removedTables);
                
            // Remove fields from these tables in selectedFields
            const selectedFieldsToRemove = Array.from(selectedFields.options)
                .filter(opt => {
                    const [table, field] = opt.value.split('.');
                    return removedTables.includes(table);
                });
                
            // Move these fields back to availableFields
            selectedFieldsToRemove.forEach(option => {
                const newOption = option.cloneNode(true);
                availableFields.appendChild(newOption);
                selectedFields.removeChild(option);
            });
            
            // Update the hidden input with the remaining selected fields
            updateSelectedFieldsInput();
            
            // Remove any filters that reference the removed tables
            filters = filters.filter(f => !removedTables.includes(f.table));
            renderFilters();
            
            // Clear sort if it references a removed table
            if (currentSort && removedTables.includes(currentSort.table)) {
                clearSort();
            }
            
            // Update available fields which will also update filter and sort fields
            updateAvailableFields();
            
            console.log('Available tables after:', Array.from(availableTables.options).map(opt => opt.value));
            console.log('Selected tables after:', Array.from(selectedTables.options).map(opt => opt.value));
        } else {
            console.log('Failed to move options');
        }
    });

    // Event listeners for field movement
    addFieldBtn.addEventListener('click', function() {
        if (moveSelectedOptions(availableFields, selectedFields)) {
            updateSelectedFieldsInput();
        }
    });

    removeFieldBtn.addEventListener('click', function() {
        if (moveSelectedOptions(selectedFields, availableFields)) {
            updateSelectedFieldsInput();
        }
    });

    // Update the hidden input with selected fields
    function updateSelectedFieldsInput() {
        const selectedFieldsByTable = {};
        Array.from(selectedFields.options).forEach(option => {
            const [table, field] = option.value.split('.');
            if (!selectedFieldsByTable[table]) {
                selectedFieldsByTable[table] = [];
            }
            selectedFieldsByTable[table].push(field);
        });
        selectedFieldsInput.value = JSON.stringify(selectedFieldsByTable);
    }

    // Form validation
    document.getElementById('reportForm').addEventListener('submit', function(e) {
        const selectedFieldsList = Array.from(selectedFields.options);
        if (selectedFieldsList.length === 0) {
            e.preventDefault();
            showMessage('Please select at least one field for the report.', 'error');
            return;
        }
        updateSelectedFieldsInput();
    });

    // Also update fields if user manually changes selected tables
    selectedTables.addEventListener('change', updateAvailableFields);

    // Initialize form with existing data if in edit mode
    if (window.initialData) {
        try {
            console.log('Initializing with data:', window.initialData);
            
            // Initialize selected tables
            if (Array.isArray(window.initialData.selectedTables)) {
                window.initialData.selectedTables.forEach(tableName => {
                    const option = Array.from(availableTables.options).find(opt => opt.value === tableName);
                    if (option) {
                        const newOption = option.cloneNode(true);
                        selectedTables.appendChild(newOption);
                        option.remove();
                    }
                });
                
                // Update available fields and wait for them to load before initializing everything else
                updateAvailableFields().then(() => {
                    console.log('Fields loaded, initializing form data');
                    
                    // Initialize selected fields
                    if (window.initialData.selectedFields && typeof window.initialData.selectedFields === 'object') {
                        Object.entries(window.initialData.selectedFields).forEach(([table, fields]) => {
                            if (Array.isArray(fields)) {
                                fields.forEach(fieldName => {
                                    const fullFieldName = `${table}.${fieldName}`;
                                    const option = Array.from(availableFields.options).find(opt => opt.value === fullFieldName);
                                    if (option) {
                                        const newOption = option.cloneNode(true);
                                        selectedFields.appendChild(newOption);
                                        option.remove();
                                    }
                                });
                            }
                        });
                        updateSelectedFieldsInput();
                    }
                    
                    // Initialize filters
                    if (window.initialData.filters) {
                        filters = window.initialData.filters;
                        renderFilters();
                    }
                    
                    // Initialize sort
                    if (window.initialData.sortBy) {
                        const sortConfig = window.initialData.sortBy;
                        const table = Object.keys(sortConfig)[0];
                        if (table) {
                            const field = sortConfig[table].field;
                            const fullFieldName = `${table}.${field}`;
                            if (Array.from(sortField.options).some(opt => opt.value === fullFieldName)) {
                                sortField.value = fullFieldName;
                                sortDirection.value = window.initialData.sortDirection || 'asc';
                                applySortBtn.click();
                            }
                        }
                    }
                    
                    // Initialize aggregations
                    if (window.initialData.aggregations) {
                        console.log('Initializing aggregations:', window.initialData.aggregations);
                        aggregations = window.initialData.aggregations;
                        renderAggregations();
                        
                        // Update aggregation fields dropdown
                        updateAggregationFields();
                    }
                });
            }
        } catch (error) {
            console.error('Error initializing form data:', error);
            showMessage('Error loading report data. Please try again.', 'error');
        }
    }

    // Add aggregation field updates to the updateAvailableFields function
    const originalUpdateAvailableFields = updateAvailableFields;
    updateAvailableFields = function() {
        originalUpdateAvailableFields();
        updateAggregationFields();
    };
    
    // Initialize aggregations if in edit mode
    if (window.initialData && window.initialData.aggregations) {
        aggregations = window.initialData.aggregations;
        renderAggregations();
    }
});

// --- Filter Builder Logic ---
const filterField = document.getElementById('filterField');
const filterOperator = document.getElementById('filterOperator');
const filterValue = document.getElementById('filterValue');
const filterDateValue = document.getElementById('filterDateValue');
const filterDateTimeValue = document.getElementById('filterDateTimeValue');
const filterNumberValue = document.getElementById('filterNumberValue');
const filterValueDropdown = document.getElementById('filterValueDropdown');
const filterValueHint = document.getElementById('filterValueHint');
const addFilterBtn = document.getElementById('addFilterBtn');
const currentFilters = document.getElementById('currentFilters');
const editFilterBtn = document.getElementById('editFilterBtn');
const removeFilterBtn = document.getElementById('removeFilterBtn');
const filtersInput = document.getElementById('id_filters');

let filters = [];
let editingIndex = null;
let autocompleteTimeout = null;
let currentFieldType = 'text';

// Update operator options based on field type
filterField.addEventListener('change', function() {
    const [table, field] = this.value.split('.');
    const model = availableModels[table];
    if (model) {
        const fieldInfo = model.fields.find(f => f.name === field);
        if (fieldInfo) {
            currentFieldType = fieldInfo.type;
            updateOperatorOptions(fieldInfo.type);
            updateValueInput(fieldInfo.type);
        }
    }
});

// Update value input based on operator
filterOperator.addEventListener('change', function() {
    updateValueInput(currentFieldType, this.value);
});

function updateOperatorOptions(fieldType) {
    const operator = filterOperator;
    operator.innerHTML = '';
    
    const addOption = (value, label, group) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        group.appendChild(option);
    };
    
    // Create option groups
    const textGroup = document.createElement('optgroup');
    textGroup.label = 'Text';
    const numericGroup = document.createElement('optgroup');
    numericGroup.label = 'Numeric';
    const dateGroup = document.createElement('optgroup');
    dateGroup.label = 'Date';
    const listGroup = document.createElement('optgroup');
    listGroup.label = 'Lists';
    const nullGroup = document.createElement('optgroup');
    nullGroup.label = 'Null';
    
    // Add common operators
    addOption('equals', 'Equals', textGroup);
    addOption('not_equals', 'Does Not Equal', textGroup);
    
    // Add type-specific operators
    switch(fieldType) {
        case 'CharField':
        case 'TextField':
            addOption('contains', 'Contains', textGroup);
            addOption('not_contains', 'Does Not Contain', textGroup);
            addOption('starts_with', 'Starts With', textGroup);
            addOption('ends_with', 'Ends With', textGroup);
            operator.appendChild(textGroup);
            break;
            
        case 'IntegerField':
        case 'FloatField':
        case 'DecimalField':
            addOption('gt', 'Greater Than', numericGroup);
            addOption('gte', 'Greater Than or Equal', numericGroup);
            addOption('lt', 'Less Than', numericGroup);
            addOption('lte', 'Less Than or Equal', numericGroup);
            operator.appendChild(numericGroup);
            break;
            
        case 'DateTimeField':
        case 'DateField':
            addOption('gt', 'After', dateGroup);
            addOption('gte', 'On or After', dateGroup);
            addOption('lt', 'Before', dateGroup);
            addOption('lte', 'On or Before', dateGroup);
            operator.appendChild(dateGroup);
            break;
    }
    
    // Add list operators for all types
    addOption('in', 'In List', listGroup);
    addOption('not_in', 'Not In List', listGroup);
    operator.appendChild(listGroup);
    
    // Add null operators for all types
    addOption('is_null', 'Is Empty', nullGroup);
    addOption('is_not_null', 'Is Not Empty', nullGroup);
    operator.appendChild(nullGroup);
}

function updateValueInput(fieldType, operator = 'equals') {
    // Hide all inputs first
    filterValue.classList.add('hidden');
    filterDateValue.classList.add('hidden');
    filterDateTimeValue.classList.add('hidden');
    filterNumberValue.classList.add('hidden');
    filterValueDropdown.classList.add('hidden');
    filterValueHint.textContent = '';
    
    // Show appropriate input based on field type and operator
    if (operator === 'is_null' || operator === 'is_not_null') {
        // No value input needed for null operators
        return;
    }
    
    if (operator === 'in' || operator === 'not_in') {
        filterValue.classList.remove('hidden');
        filterValueHint.textContent = 'Enter multiple values separated by commas';
        return;
    }
    
    switch(fieldType) {
        case 'DateTimeField':
            filterDateTimeValue.classList.remove('hidden');
            break;
        case 'DateField':
            filterDateValue.classList.remove('hidden');
            break;
        case 'IntegerField':
        case 'FloatField':
        case 'DecimalField':
            filterNumberValue.classList.remove('hidden');
            break;
        default:
            filterValue.classList.remove('hidden');
            if (operator === 'contains' || operator === 'not_contains') {
                filterValueDropdown.classList.remove('hidden');
            }
    }
}

// Add or update filter
addFilterBtn.addEventListener('click', function() {
    const field = filterField.value;
    const operator = filterOperator.value;
    let value;
    
    // Get value from appropriate input
    if (operator === 'is_null' || operator === 'is_not_null') {
        value = '';
    } else {
        switch(currentFieldType) {
            case 'DateTimeField':
                value = filterDateTimeValue.value;
                break;
            case 'DateField':
                value = filterDateValue.value;
                break;
            case 'IntegerField':
            case 'FloatField':
            case 'DecimalField':
                value = filterNumberValue.value;
                break;
            default:
                value = filterValue.value;
        }
    }
    
    if (!field || !operator || (operator !== 'is_null' && operator !== 'is_not_null' && !value)) {
        showMessage('Please select a field, operator, and enter a value for the filter.', 'error');
        return;
    }
    
    // Split the field into table and field name
    const [table, fieldName] = field.split('.');
    const filterObj = {
        table,
        field: fieldName,
        operator,
        value
    };
    
    if (editingIndex !== null) {
        filters[editingIndex] = filterObj;
        editingIndex = null;
        addFilterBtn.textContent = 'Add Filter';
    } else {
        filters.push(filterObj);
    }
    
    renderFilters();
    clearFilterBuilder();
});

// Render current filters in the listbox
function renderFilters() {
    currentFilters.innerHTML = '';
    filters.forEach((f, idx) => {
        const option = document.createElement('option');
        option.value = idx;
        option.textContent = `${f.table}.${f.field} ${operatorLabel(f.operator)} ${formatFilterValue(f)}`;
        currentFilters.appendChild(option);
    });
    filtersInput.value = JSON.stringify(filters);
}

function operatorLabel(op) {
    const labels = {
        'equals': '=',
        'not_equals': '≠',
        'contains': 'contains',
        'not_contains': 'not contains',
        'gt': '>',
        'gte': '≥',
        'lt': '<',
        'lte': '≤',
        'starts_with': 'starts with',
        'ends_with': 'ends with',
        'in': 'in',
        'not_in': 'not in',
        'is_null': 'is empty',
        'is_not_null': 'is not empty'
    };
    return labels[op] || op;
}

function formatFilterValue(filter) {
    if (filter.operator === 'is_null' || filter.operator === 'is_not_null') {
        return '';
    }
    if (filter.operator === 'in' || filter.operator === 'not_in') {
        return '(' + filter.value + ')';
    }
    return '"' + filter.value + '"';
}

// Edit filter
editFilterBtn.addEventListener('click', function() {
    const idx = currentFilters.selectedIndex;
    if (idx === -1) return;
    
    const f = filters[idx];
    filterField.value = `${f.table}.${f.field}`;
    filterField.dispatchEvent(new Event('change')); // Trigger field type update
    
    setTimeout(() => {
        filterOperator.value = f.operator;
        filterOperator.dispatchEvent(new Event('change')); // Trigger operator update
        
        // Set value in appropriate input
        if (f.operator !== 'is_null' && f.operator !== 'is_not_null') {
            switch(currentFieldType) {
                case 'DateTimeField':
                    filterDateTimeValue.value = f.value;
                    break;
                case 'DateField':
                    filterDateValue.value = f.value;
                    break;
                case 'IntegerField':
                case 'FloatField':
                case 'DecimalField':
                    filterNumberValue.value = f.value;
                    break;
                default:
                    filterValue.value = f.value;
            }
        }
        
        editingIndex = idx;
        addFilterBtn.textContent = 'Update Filter';
    }, 100);
});

// Remove filter
removeFilterBtn.addEventListener('click', function() {
    const idx = currentFilters.selectedIndex;
    if (idx === -1) return;
    filters.splice(idx, 1);
    renderFilters();
    clearFilterBuilder();
});

// Clear builder
function clearFilterBuilder() {
    filterField.selectedIndex = 0;
    filterOperator.selectedIndex = 0;
    filterValue.value = '';
    filterDateValue.value = '';
    filterDateTimeValue.value = '';
    filterNumberValue.value = '';
    filterValueDropdown.innerHTML = '';
    filterValueDropdown.classList.add('hidden');
    editingIndex = null;
    addFilterBtn.textContent = 'Add Filter';
}

// Autocomplete functionality
filterValue.addEventListener('input', function() {
    const field = filterField.value;
    const searchTerm = this.value;

    // Clear any pending timeout
    if (autocompleteTimeout) {
        clearTimeout(autocompleteTimeout);
    }

    // Set a new timeout to prevent too many requests
    autocompleteTimeout = setTimeout(() => {
        if (!field || !searchTerm) {
            filterValueDropdown.innerHTML = '';
            filterValueDropdown.classList.add('hidden');
            return;
        }

        // Fetch autocomplete suggestions
        fetch(`/reporting/api/get-field-values/?field=${encodeURIComponent(field)}&term=${encodeURIComponent(searchTerm)}`)
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    console.error(data.error);
                    return;
                }
                
                filterValueDropdown.innerHTML = '';
                if (data.values.length > 0) {
                    data.values.forEach(value => {
                        const option = document.createElement('option');
                        option.value = value;
                        option.textContent = value;
                        filterValueDropdown.appendChild(option);
                    });
                    filterValueDropdown.classList.remove('hidden');
                } else {
                    filterValueDropdown.classList.add('hidden');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                filterValueDropdown.classList.add('hidden');
            });
    }, 300); // 300ms delay
});

// Handle dropdown selection
filterValueDropdown.addEventListener('click', function(e) {
    if (e.target.tagName === 'OPTION') {
        filterValue.value = e.target.value;
        this.classList.add('hidden');
    }
});

// Hide dropdown when clicking outside
document.addEventListener('click', function(e) {
    if (!filterValue.contains(e.target) && !filterValueDropdown.contains(e.target)) {
        filterValueDropdown.classList.add('hidden');
    }
});

// --- Sort Functionality ---
const sortField = document.getElementById('sortField');
const sortDirection = document.getElementById('sortDirection');
const applySortBtn = document.getElementById('applySortBtn');
const currentSortDisplay = document.getElementById('currentSortDisplay');

// Update sort fields when available fields change
function updateSortFields() {
    sortField.innerHTML = '<option value="">Select a field...</option>';
    
    // Add options from both available and selected fields
    const allFields = new Set();
    
    // Add from available fields
    Array.from(availableFields.options).forEach(opt => {
        if (!allFields.has(opt.value)) {
            const option = document.createElement('option');
            option.value = opt.value;
            option.textContent = opt.textContent;
            sortField.appendChild(option);
            allFields.add(opt.value);
        }
    });
    
    // Add from selected fields
    Array.from(selectedFields.options).forEach(opt => {
        if (!allFields.has(opt.value)) {
            const option = document.createElement('option');
            option.value = opt.value;
            option.textContent = opt.textContent;
            sortField.appendChild(option);
            allFields.add(opt.value);
        }
    });
    
    // If there's a current sort, try to restore it
    if (window.initialData && window.initialData.sortBy) {
        const sortConfig = window.initialData.sortBy;
        const table = Object.keys(sortConfig)[0];
        if (table) {
            const field = sortConfig[table].field;
            const fullFieldName = `${table}.${field}`;
            if (Array.from(sortField.options).some(opt => opt.value === fullFieldName)) {
                sortField.value = fullFieldName;
                sortDirection.value = window.initialData.sortDirection || 'asc';
                applySortBtn.click(); // Trigger sort application
            }
        }
    }
}

// Apply sort configuration
applySortBtn.addEventListener('click', function() {
    const fieldValue = sortField.value;
    if (!fieldValue) {
        showMessage('Please select a field to sort by', 'error');
        return;
    }
    
    const [table, field] = fieldValue.split('.');
    currentSort = {
        table: table,
        field: field,
        direction: sortDirection.value
    };
    
    // Update display
    const fieldOption = sortField.options[sortField.selectedIndex];
    const directionText = sortDirection.value === 'asc' ? 'ascending' : 'descending';
    currentSortDisplay.innerHTML = `
        <p class="text-sm font-medium">
            Sorting by: ${fieldOption.textContent} (${directionText})
            <button type="button" class="ml-2 text-red-600 hover:text-red-800" onclick="clearSort()">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 inline" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                </svg>
            </button>
        </p>
    `;
    
    // Update hidden inputs for form submission
    const sortConfig = {
        [table]: {
            field: field,
            direction: sortDirection.value
        }
    };
    document.getElementById('sort_by').value = JSON.stringify(sortConfig);
    document.getElementById('sort_direction').value = sortDirection.value;
});

// Clear sort configuration
window.clearSort = function() {
    currentSort = null;
    sortField.value = '';
    sortDirection.value = 'asc';
    currentSortDisplay.innerHTML = '<p class="text-sm text-gray-500">No sorting applied</p>';
    document.getElementById('sort_by').value = '{}';
    document.getElementById('sort_direction').value = 'asc';
};

// --- Aggregation Logic ---
const aggregationField = document.getElementById('aggregationField');
const aggregationType = document.getElementById('aggregationType');
const aggregationLabel = document.getElementById('aggregationLabel');
const addAggregationBtn = document.getElementById('addAggregationBtn');
const currentAggregations = document.getElementById('currentAggregations');
const editAggregationBtn = document.getElementById('editAggregationBtn');
const removeAggregationBtn = document.getElementById('removeAggregationBtn');
const aggregationsInput = document.getElementById('id_aggregations');

let aggregations = {};
let editingAggregation = null;

// Function to update aggregation fields
function updateAggregationFields() {
    console.log('Updating aggregation fields');
    console.log('Current availableModels:', availableModels);
    console.log('Current aggregations:', aggregations);
    
    aggregationField.innerHTML = '<option value="">Select a field...</option>';
    
    // Add all numeric fields to the aggregation dropdown
    const allFields = new Set();
    
    // Function to add field to dropdown if it supports aggregation
    const addFieldIfAggregatable = (table, fieldInfo) => {
        console.log('Checking field:', table, fieldInfo);
        if (fieldInfo.supports_aggregation || aggregationType.value === 'count') {
            const fieldPath = `${table}.${fieldInfo.name}`;
            if (!allFields.has(fieldPath)) {
                const option = document.createElement('option');
                option.value = fieldPath;
                option.textContent = `${table.charAt(0).toUpperCase() + table.slice(1)} - ${fieldInfo.verbose_name}`;
                option.dataset.type = fieldInfo.type;
                aggregationField.appendChild(option);
                allFields.add(fieldPath);
                console.log('Added aggregatable field:', fieldPath);
            }
        }
    };
    
    // Add from available models
    if (availableModels) {
        Object.entries(availableModels).forEach(([table, fields]) => {
            fields.forEach(fieldInfo => {
                addFieldIfAggregatable(table, fieldInfo);
            });
        });
    }
    
    // Clear any existing aggregation values if not in edit mode
    if (!window.initialData || !window.initialData.aggregations) {
        clearAggregationBuilder();
    }
    
    console.log('Aggregation fields updated, current options:', Array.from(aggregationField.options).map(opt => opt.value));
}

// Add or update aggregation
addAggregationBtn.addEventListener('click', function() {
    const field = aggregationField.value;
    const type = aggregationType.value;
    const label = aggregationLabel.value.trim();
    
    if (!field || !type) {
        showMessage('Please select a field and aggregation type.', 'error');
        return;
    }
    
    const [table, fieldName] = field.split('.');
    const fieldOption = aggregationField.options[aggregationField.selectedIndex];
    const defaultLabel = `${type.charAt(0).toUpperCase() + type.slice(1)} of ${fieldOption.textContent}`;
    
    const aggregationConfig = {
        type: type,
        label: label || defaultLabel
    };
    
    if (editingAggregation) {
        delete aggregations[editingAggregation];
        editingAggregation = null;
        addAggregationBtn.textContent = 'Add Aggregation';
    }
    
    aggregations[field] = aggregationConfig;
    renderAggregations();
    clearAggregationBuilder();
});

// Render current aggregations in the listbox
function renderAggregations() {
    console.log('Rendering aggregations:', aggregations);
    currentAggregations.innerHTML = '';
    Object.entries(aggregations).forEach(([field, config]) => {
        const option = document.createElement('option');
        option.value = field;
        option.textContent = `${config.label} (${field})`;
        currentAggregations.appendChild(option);
    });
    aggregationsInput.value = JSON.stringify(aggregations);
    console.log('Updated aggregations input value:', aggregationsInput.value);
}

// Edit aggregation
editAggregationBtn.addEventListener('click', function() {
    const field = currentAggregations.value;
    if (!field) return;
    
    const config = aggregations[field];
    if (!config) return;
    
    aggregationField.value = field;
    aggregationType.value = config.type;
    aggregationLabel.value = config.label;
    
    editingAggregation = field;
    addAggregationBtn.textContent = 'Update Aggregation';
});

// Remove aggregation
removeAggregationBtn.addEventListener('click', function() {
    const field = currentAggregations.value;
    if (!field) return;
    
    delete aggregations[field];
    renderAggregations();
    clearAggregationBuilder();
});

// Clear builder
function clearAggregationBuilder() {
    aggregationField.selectedIndex = 0;
    aggregationType.selectedIndex = 0;
    aggregationLabel.value = '';
    editingAggregation = null;
    addAggregationBtn.textContent = 'Add Aggregation';
} 