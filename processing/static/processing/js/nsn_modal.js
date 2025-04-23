// NSN Modal functionality

// Configuration
const NSN_MODAL_CONFIG = {
    minSearchLength: 3,
    pageSize: 10,
    endpoints: {
        search: '/contracts/api/options/nsn/',
        match: '/processing/match-nsn/',
        create: '/contracts/api/nsn/create/'
    }
};

// Core variables
let currentNsnClinId = null;
let nsnCurrentPage = 1;

// Core Modal Functions
function openNsnModal(clinId, nsnText, nsnDescription) {
    currentNsnClinId = clinId;
    const modal = document.getElementById('nsn_modal');
    const searchInput = document.getElementById('nsn_search');
    const originalDisplay = document.getElementById('original_nsn_display');
    
    originalDisplay.textContent = `NSN: ${nsnText || 'Not specified'}`;
    if (nsnDescription) {
        originalDisplay.textContent += `\nDescription: ${nsnDescription}`;
    }
    
    searchInput.value = nsnText || '';
    modal.classList.remove('hidden');
    searchInput.focus();
    
    if (nsnText) {
        searchNsn();
    }
}

function closeNsnModal() {
    document.getElementById('nsn_modal').classList.add('hidden');
    document.getElementById('add_nsn_form').classList.add('hidden');
    currentNsnClinId = null;
}

function searchNsn() {
    const searchTerm = document.getElementById('nsn_search').value.trim();
    if (searchTerm.length < NSN_MODAL_CONFIG.minSearchLength) {
        document.getElementById('nsn_search_results').innerHTML = 
            '<div class="text-center text-gray-500 py-4">Enter at least 3 characters to search</div>';
        return;
    }
    
    document.getElementById('nsn_search_results').innerHTML = 
        '<div class="text-center py-4"><div class="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div><p class="mt-2 text-gray-600">Loading...</p></div>';
    
    fetch(`${NSN_MODAL_CONFIG.endpoints.search}?search=${encodeURIComponent(searchTerm)}&page=${nsnCurrentPage}&page_size=${NSN_MODAL_CONFIG.pageSize}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const resultsDiv = document.getElementById('nsn_search_results');
                resultsDiv.innerHTML = '';
                
                if (data.options && data.options.length > 0) {
                    let resultsHtml = '';
                    data.options.forEach(option => {
                        resultsHtml += `
                            <div class="nsn-result-item hover:bg-gray-50 p-2 cursor-pointer" 
                                 onclick="selectNsn('${option.value}', '${option.label}')">
                                <div class="font-medium">${option.label}</div>
                            </div>
                        `;
                    });
                    resultsDiv.innerHTML = resultsHtml;
                    
                    // Add pagination if needed
                    if (data.total > NSN_MODAL_CONFIG.pageSize) {
                        const totalPages = Math.ceil(data.total / NSN_MODAL_CONFIG.pageSize);
                        const paginationHtml = createPaginationControls(nsnCurrentPage, totalPages);
                        resultsDiv.innerHTML += paginationHtml;
                    }
                } else {
                    resultsDiv.innerHTML = '<div class="text-center text-gray-500 py-4">No matches found</div>';
                }
            } else {
                document.getElementById('nsn_search_results').innerHTML = 
                    '<div class="text-center text-red-500 py-4">Error searching for NSNs</div>';
            }
        })
        .catch(error => {
            console.error('Search error:', error);
            document.getElementById('nsn_search_results').innerHTML = 
                '<div class="text-center text-red-500 py-4">Error connecting to the server</div>';
        });
}

function selectNsn(id, text) {
    console.log('Selecting NSN:', { id, text });
    console.log('Current CLIN ID:', currentNsnClinId);
    
    // Update the CLIN's NSN
    fetch(`${NSN_MODAL_CONFIG.endpoints.match}${currentNsnClinId}/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
        },
        body: JSON.stringify({ id: id })
    })
    .then(response => {
        console.log('Response status:', response.status);
        if (!response.ok) {
            return response.text().then(text => {
                console.error('Error response:', text);
                throw new Error('Network response was not ok');
            });
        }
        return response.json();
    })
    .then(data => {
        console.log('Success response:', data);
        if (data.success) {
            location.reload();
        } else {
            alert(data.error || 'Error selecting NSN');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Error selecting NSN: ' + error.message);
    });
}

// Add NSN Form Functionality
function showAddNsnForm() {
    const form = document.getElementById('add_nsn_form');
    const codeInput = document.getElementById('new_nsn_code');
    const descInput = document.getElementById('new_nsn_description');
    const originalText = document.getElementById('original_nsn_display').textContent;
    
    // Parse NSN and description from original text
    const nsnMatch = originalText.match(/NSN: (.*?)(?:\nDescription: |$)/);
    const descMatch = originalText.match(/Description: (.*?)$/);
    
    form.classList.remove('hidden');
    if (nsnMatch) codeInput.value = nsnMatch[1].trim();
    if (descMatch) descInput.value = descMatch[1].trim();
}

function createNewNsn() {
    const nsnCode = document.getElementById('new_nsn_code').value.trim();
    const nsnDescription = document.getElementById('new_nsn_description').value.trim();
    
    if (!nsnCode) {
        alert('NSN code is required');
        return;
    }
    
    fetch(NSN_MODAL_CONFIG.endpoints.create, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
        },
        body: JSON.stringify({
            nsn: nsnCode,
            description: nsnDescription
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            selectNsn(data.id, nsnCode);
        } else {
            alert(data.error || 'Failed to create NSN');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Error creating NSN');
    });
}

// Pagination functions
function prevNsnPage() {
    if (nsnCurrentPage > 1) {
        nsnCurrentPage--;
        searchNsn();
    }
}

function nextNsnPage() {
    nsnCurrentPage++;
    searchNsn();
}

function createPaginationControls(currentPage, totalPages) {
    return `
        <div class="flex justify-between items-center mt-4 border-t pt-3">
            <button onclick="prevNsnPage()" class="px-3 py-1 bg-gray-200 rounded ${currentPage === 1 ? 'opacity-50 cursor-not-allowed' : 'hover:bg-gray-300'}" ${currentPage === 1 ? 'disabled' : ''}>
                Previous
            </button>
            <span class="text-sm text-gray-600">Page ${currentPage} of ${totalPages}</span>
            <button onclick="nextNsnPage()" class="px-3 py-1 bg-gray-200 rounded ${currentPage === totalPages ? 'opacity-50 cursor-not-allowed' : 'hover:bg-gray-300'}" ${currentPage === totalPages ? 'disabled' : ''}>
                Next
            </button>
        </div>
    `;
}

// Add event listeners when the document is loaded
document.addEventListener('DOMContentLoaded', function() {
    // Handle NSN modal
    document.querySelectorAll('[data-action="open-nsn"]').forEach(button => {
        button.addEventListener('click', function() {
            const id = this.dataset.id;
            const nsn = this.dataset.nsn;
            const description = this.dataset.description;
            openNsnModal(id, nsn, description);
        });
    });

    // Add event listeners for NSN search
    const searchInput = document.getElementById('nsn_search');
    
    if (searchInput) {
        searchInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                searchNsn();
            }
        });
    }
}); 