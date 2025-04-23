// Configuration
const BUYER_MODAL_CONFIG = {
    minSearchLength: 3,
    pageSize: 10,
    endpoints: {
        search: '/contracts/api/options/buyer/',
        match: '/processing/match-buyer/',
        create: '/contracts/api/buyers/create/'
    },
    selectors: {
        modal: '#buyer_modal',
        searchInput: '#buyer_search',
        searchResults: '#buyer_search_results',
        originalDisplay: '#original_buyer_display',
        addForm: '#add_buyer_form',
        newBuyerName: '#new_buyer_name'
    },
    messages: {
        minLength: 'Enter at least 3 characters to search',
        noResults: 'No matches found',
        error: 'Error searching for buyer',
        serverError: 'Error connecting to the server',
        loading: '<div class="text-center py-4"><div class="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div><p class="mt-2 text-gray-600">Loading...</p></div>'
    }
};

// Core Modal Functions
function openBuyerModal(buyerText) {
    const modal = document.querySelector(BUYER_MODAL_CONFIG.selectors.modal);
    const searchInput = document.querySelector(BUYER_MODAL_CONFIG.selectors.searchInput);
    const originalDisplay = document.querySelector(BUYER_MODAL_CONFIG.selectors.originalDisplay);
    
    originalDisplay.textContent = `Buyer: ${buyerText || 'Not specified'}`;
    searchInput.value = buyerText || '';
    modal.classList.remove('hidden');
    searchInput.focus();
    
    if (buyerText) {
        searchBuyer();
    }
}

function closeBuyerModal() {
    document.querySelector(BUYER_MODAL_CONFIG.selectors.modal).classList.add('hidden');
}

function showAddBuyerForm() {
    const form = document.querySelector(BUYER_MODAL_CONFIG.selectors.addForm);
    const input = document.querySelector(BUYER_MODAL_CONFIG.selectors.newBuyerName);
    const originalText = document.querySelector(BUYER_MODAL_CONFIG.selectors.originalDisplay)
        .textContent.replace('Buyer: ', '');
    
    form.classList.remove('hidden');
    input.value = originalText;
}

// Search Functions
async function searchBuyer() {
    const searchTerm = document.querySelector(BUYER_MODAL_CONFIG.selectors.searchInput).value.trim();
    const resultsDiv = document.querySelector(BUYER_MODAL_CONFIG.selectors.searchResults);
    
    // Validate search term
    if (searchTerm.length < BUYER_MODAL_CONFIG.minSearchLength) {
        resultsDiv.innerHTML = `<div class="text-center text-gray-500 py-4">${BUYER_MODAL_CONFIG.messages.minLength}</div>`;
        return;
    }
    
    // Show loading state
    resultsDiv.innerHTML = BUYER_MODAL_CONFIG.messages.loading;
    
    try {
        const response = await fetch(
            `${BUYER_MODAL_CONFIG.endpoints.search}?search=${encodeURIComponent(searchTerm)}&page=1&page_size=${BUYER_MODAL_CONFIG.pageSize}`
        );
        const data = await response.json();
        
        if (data.success) {
            displaySearchResults(data.options, resultsDiv);
        } else {
            resultsDiv.innerHTML = `<div class="text-center text-red-500 py-4">${BUYER_MODAL_CONFIG.messages.error}</div>`;
        }
    } catch (error) {
        console.error('Search error:', error);
        resultsDiv.innerHTML = `<div class="text-center text-red-500 py-4">${BUYER_MODAL_CONFIG.messages.serverError}</div>`;
    }
}

function displaySearchResults(options, resultsDiv) {
    if (!options || options.length === 0) {
        resultsDiv.innerHTML = `<div class="text-center text-gray-500 py-4">${BUYER_MODAL_CONFIG.messages.noResults}</div>`;
        return;
    }
    
    const resultsHtml = options.map(option => `
        <div class="buyer-result-item hover:bg-gray-50 p-2 cursor-pointer" 
             onclick="selectBuyer('${option.value}', '${option.label}')">
            <div class="font-medium">${option.label}</div>
        </div>
    `).join('');
    
    resultsDiv.innerHTML = resultsHtml;
}

// Selection and Creation Functions
async function selectBuyer(id, text) {
    try {
        const response = await fetch(`${BUYER_MODAL_CONFIG.endpoints.match}${processContractId}/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
            },
            body: JSON.stringify({ id: id })
        });
        
        const data = await response.json();
        if (data.success) {
            location.reload();
        } else {
            alert(data.error || 'Error selecting buyer');
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Error selecting buyer: ' + error.message);
    }
}

async function createNewBuyer() {
    const buyerName = document.querySelector(BUYER_MODAL_CONFIG.selectors.newBuyerName).value.trim();
    
    if (!buyerName) {
        alert('Buyer name is required');
        return;
    }
    
    try {
        const response = await fetch(BUYER_MODAL_CONFIG.endpoints.create, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
            },
            body: JSON.stringify({
                buyer_text: buyerName
            })
        });
        
        const data = await response.json();
        if (data.success) {
            selectBuyer(data.id, buyerName);
        } else {
            alert(data.error || 'Failed to create buyer');
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Error creating buyer');
    }
}

// Event Listeners
document.addEventListener('DOMContentLoaded', function() {
    // Handle Buyer modal
    document.querySelectorAll('[data-action="open-buyer"]').forEach(button => {
        button.addEventListener('click', function() {
            const buyer = this.dataset.buyer;
            openBuyerModal(buyer);
        });
    });

    // Add event listeners for buyer search
    const buyerSearchInput = document.querySelector(BUYER_MODAL_CONFIG.selectors.searchInput);
    if (buyerSearchInput) {
        buyerSearchInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                searchBuyer();
            }
        });
    }
});
