// Supplier Modal Management
let currentSupplierPage = 1;
let totalSupplierPages = 1;
let selectedSupplierId = null;
let supplierSearchTimeout = null;

// Modal Open/Close Functions
function openSupplierModal() {
    document.getElementById('supplier_modal').classList.remove('hidden');
    performSupplierSearch();
}

function closeSupplierModal() {
    document.getElementById('supplier_modal').classList.remove('hidden');
    resetSupplierSearch();
}

function openSupplierCreateModal() {
    document.getElementById('supplier_create_modal').classList.remove('hidden');
}

function closeSupplierCreateModal() {
    document.getElementById('supplier_create_modal').classList.add('hidden');
    document.getElementById('supplier_create_form').reset();
}

// Search and Navigation Functions
function performSupplierSearch(page = 1) {
    const searchQuery = document.getElementById('supplier_search').value;
    currentSupplierPage = page;

    // Show loading state
    document.getElementById('supplier_results').innerHTML = '<tr><td colspan="4" class="text-center py-4">Loading...</td></tr>';

    fetch(`/api/suppliers/search/?q=${encodeURIComponent(searchQuery)}&page=${page}`)
        .then(response => response.json())
        .then(data => {
            updateSupplierResults(data);
            updateSupplierPagination(data.total_pages);
        })
        .catch(error => {
            console.error('Error searching suppliers:', error);
            document.getElementById('supplier_results').innerHTML = 
                '<tr><td colspan="4" class="text-center py-4 text-red-500">Error loading suppliers</td></tr>';
        });
}

function updateSupplierResults(data) {
    const resultsContainer = document.getElementById('supplier_results');
    resultsContainer.innerHTML = '';

    if (data.results.length === 0) {
        resultsContainer.innerHTML = '<tr><td colspan="4" class="text-center py-4">No suppliers found</td></tr>';
        return;
    }

    data.results.forEach(supplier => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td class="px-6 py-4 whitespace-nowrap">${supplier.name}</td>
            <td class="px-6 py-4 whitespace-nowrap">${supplier.cage_code}</td>
            <td class="px-6 py-4 whitespace-nowrap">${supplier.location || '-'}</td>
            <td class="px-6 py-4 whitespace-nowrap">
                <button onclick="selectSupplier('${supplier.id}', '${supplier.name}')"
                        class="text-blue-600 hover:text-blue-800">
                    Select
                </button>
            </td>
        `;
        resultsContainer.appendChild(row);
    });
}

function updateSupplierPagination(totalPages) {
    totalSupplierPages = totalPages;
    const prevButton = document.getElementById('supplier_prev_page');
    const nextButton = document.getElementById('supplier_next_page');
    const pageInfo = document.getElementById('supplier_page_info');

    prevButton.disabled = currentSupplierPage === 1;
    nextButton.disabled = currentSupplierPage === totalPages;
    pageInfo.textContent = `Page ${currentSupplierPage} of ${totalPages}`;
}

function resetSupplierSearch() {
    document.getElementById('supplier_search').value = '';
    currentSupplierPage = 1;
    selectedSupplierId = null;
}

// Supplier Selection and Creation
function selectSupplier(id, name) {
    selectedSupplierId = id;
    // Update the form field or trigger callback
    const event = new CustomEvent('supplierSelected', {
        detail: { id, name }
    });
    document.dispatchEvent(event);
    closeSupplierModal();
}

// Event Listeners
document.addEventListener('DOMContentLoaded', function() {
    // Search input with debounce
    const searchInput = document.getElementById('supplier_search');
    searchInput.addEventListener('input', function() {
        clearTimeout(supplierSearchTimeout);
        supplierSearchTimeout = setTimeout(() => performSupplierSearch(), 300);
    });

    // Search button
    document.getElementById('supplier_search_btn').addEventListener('click', () => performSupplierSearch());

    // Pagination
    document.getElementById('supplier_prev_page').addEventListener('click', () => {
        if (currentSupplierPage > 1) {
            performSupplierSearch(currentSupplierPage - 1);
        }
    });

    document.getElementById('supplier_next_page').addEventListener('click', () => {
        if (currentSupplierPage < totalSupplierPages) {
            performSupplierSearch(currentSupplierPage + 1);
        }
    });

    // Modal controls
    document.getElementById('close_supplier_modal').addEventListener('click', closeSupplierModal);
    document.getElementById('create_new_supplier_btn').addEventListener('click', openSupplierCreateModal);
    document.getElementById('close_supplier_create_modal').addEventListener('click', closeSupplierCreateModal);

    // Supplier creation form
    document.getElementById('supplier_create_form').addEventListener('submit', function(e) {
        e.preventDefault();
        const formData = new FormData(this);
        const supplierData = Object.fromEntries(formData.entries());

        fetch('/contracts/api/suppliers/create/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify(supplierData)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const supplierId = data.supplier_id || data.id;
                selectSupplier(supplierId, data.name || supplierData.name);
                closeSupplierCreateModal();
                // Refresh the search results
                performSupplierSearch();
                if (data.duplicate && data.message) {
                    alert(data.message);
                }
            } else {
                throw new Error(data.error || 'Failed to create supplier');
            }
        })
        .catch(error => {
            console.error('Error creating supplier:', error);
            alert('Failed to create supplier. Please try again.');
        });
    });
});

// Utility Functions
function getCsrfToken() {
    return document.querySelector('[name=csrfmiddlewaretoken]').value;
} 
