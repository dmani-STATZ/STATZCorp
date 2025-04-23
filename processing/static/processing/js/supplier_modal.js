// Configuration
const SUPPLIER_MODAL_CONFIG = {
    minSearchLength: 3,
    pageSize: 10,
    endpoints: {
        search: '/contracts/api/options/supplier/',
        match: '/processing/match-supplier/'
    },
    selectors: {
        modal: '#supplier_modal',
        searchInput: '#supplier_search',
        searchResults: '#supplier_search_results',
        originalDisplay: '#original_supplier_display',
        addForm: '#add_supplier_form',
        newSupplierName: '#new_supplier_name',
        newSupplierCageCode: '#new_supplier_cage_code'
    }
};

// State Management
let currentSupplierClinId = null;
let supplierCurrentPage = 1;

// Core Modal Functions
function openSupplierModal(clinId, supplierText) {
    currentSupplierClinId = clinId;
    const modal = document.querySelector(SUPPLIER_MODAL_CONFIG.selectors.modal);
    const searchInput = document.querySelector(SUPPLIER_MODAL_CONFIG.selectors.searchInput);
    const originalDisplay = document.querySelector(SUPPLIER_MODAL_CONFIG.selectors.originalDisplay);
    
    originalDisplay.textContent = `Supplier: ${supplierText || 'Not specified'}`;
    searchInput.value = supplierText || '';
    modal.classList.remove('hidden');
    searchInput.focus();
    
    if (supplierText) {
        searchSupplier();
    }
}

function closeSupplierModal() {
    document.querySelector(SUPPLIER_MODAL_CONFIG.selectors.modal).classList.add('hidden');
    currentSupplierClinId = null;
    // Reset form state
    document.querySelector(SUPPLIER_MODAL_CONFIG.selectors.addForm).classList.add('hidden');
}

function showAddSupplierForm() {
    document.querySelector(SUPPLIER_MODAL_CONFIG.selectors.addForm).classList.remove('hidden');
}

// Search Functions
async function searchSupplier() {
    const searchTerm = document.querySelector(SUPPLIER_MODAL_CONFIG.selectors.searchInput).value.trim();
    const resultsDiv = document.querySelector(SUPPLIER_MODAL_CONFIG.selectors.searchResults);

    if (searchTerm.length < SUPPLIER_MODAL_CONFIG.minSearchLength) {
        resultsDiv.innerHTML = '<div class="text-center text-gray-500 py-4">Enter at least 3 characters to search</div>';
        return;
    }
    
    // Show loading state
    resultsDiv.innerHTML = '<div class="text-center py-4"><div class="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div><p class="mt-2 text-gray-600">Loading...</p></div>';
    
    try {
        const response = await fetch(
            `${SUPPLIER_MODAL_CONFIG.endpoints.search}?search=${encodeURIComponent(searchTerm)}&page=${supplierCurrentPage}&page_size=${SUPPLIER_MODAL_CONFIG.pageSize}`,
            {
                headers: {
                    'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
                }
            }
        );
        const data = await response.json();

        if (data.success) {
            if (data.options && data.options.length > 0) {
                resultsDiv.innerHTML = data.options.map(option => `
                    <div class="supplier-result-item hover:bg-gray-50 p-2 cursor-pointer" 
                         onclick="selectSupplier('${option.value}', '${option.label}')">
                        <div class="font-medium">${option.label}</div>
                    </div>
                `).join('');
            } else {
                resultsDiv.innerHTML = '<div class="text-center text-gray-500 py-4">No matches found</div>';
            }
        } else {
            resultsDiv.innerHTML = '<div class="text-center text-red-500 py-4">Error searching for supplier</div>';
        }
    } catch (error) {
        console.error('Search error:', error);
        resultsDiv.innerHTML = '<div class="text-center text-red-500 py-4">Error connecting to the server</div>';
    }
}

async function selectSupplier(id, text) {
    try {
        const response = await fetch(`${SUPPLIER_MODAL_CONFIG.endpoints.match}${currentSupplierClinId}/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
            },
            body: JSON.stringify({ supplier_id: id })
        });
        
        const data = await response.json();
        if (data.success) {
            location.reload();
        } else {
            alert('Error selecting supplier');
        }
    } catch (error) {
        console.error('Error selecting supplier:', error);
        alert('Error selecting supplier');
    }
}

async function createNewSupplier() {
    const name = document.querySelector(SUPPLIER_MODAL_CONFIG.selectors.newSupplierName).value.trim();
    const cageCode = document.querySelector(SUPPLIER_MODAL_CONFIG.selectors.newSupplierCageCode).value.trim();
    
    if (!name || !cageCode) {
        alert('Please fill in all required fields');
        return;
    }
    
    try {
        const response = await fetch('/contracts/api/suppliers/create/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
            },
            body: JSON.stringify({
                name: name,
                cage_code: cageCode
            })
        });
        
        const data = await response.json();
        if (data.success) {
            // After creating, select the new supplier
            selectSupplier(data.supplier_id, name);
        } else {
            alert(data.error || 'Error creating supplier');
        }
    } catch (error) {
        console.error('Error creating supplier:', error);
        alert('Error creating supplier');
    }
}

// Event Listeners
document.addEventListener('DOMContentLoaded', function() {
    // Handle supplier modal triggers
    document.querySelectorAll('[data-action="open-supplier"]').forEach(button => {
        button.addEventListener('click', function() {
            const id = this.dataset.id;
            const supplier = this.dataset.supplier;
            openSupplierModal(id, supplier);
        });
    });

    // Add event listener for supplier search input
    const supplierSearchInput = document.querySelector(SUPPLIER_MODAL_CONFIG.selectors.searchInput);
    if (supplierSearchInput) {
        supplierSearchInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                searchSupplier();
            }
        });
    }
});
