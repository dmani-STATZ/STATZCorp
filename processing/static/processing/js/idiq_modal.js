// IDIQ Modal functionality
function openIdiqModal(idiqText) {
    const modal = document.getElementById('idiq_modal');
    const searchInput = document.getElementById('idiq_search');
    const originalDisplay = document.getElementById('original_idiq_display');
    
    originalDisplay.textContent = `IDIQ Contract: ${idiqText || 'Not specified'}`;
    searchInput.value = idiqText || '';
    modal.classList.remove('hidden');
    searchInput.focus();
    
    if (idiqText) {
        searchIdiq();
    }
}

function closeIdiqModal() {
    document.getElementById('idiq_modal').classList.add('hidden');
}

function searchIdiq() {
    const searchTerm = document.getElementById('idiq_search').value.trim();
    if (searchTerm.length < 3) {
        document.getElementById('idiq_search_results').innerHTML = 
            '<div class="text-center text-gray-500 py-4">Enter at least 3 characters to search</div>';
        return;
    }
    
    document.getElementById('idiq_search_results').innerHTML = 
        '<div class="text-center py-4"><div class="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div><p class="mt-2 text-gray-600">Loading...</p></div>';
    
    fetch(`/contracts/api/options/idiq/?search=${encodeURIComponent(searchTerm)}&page=1&page_size=10`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const resultsDiv = document.getElementById('idiq_search_results');
                resultsDiv.innerHTML = '';
                
                if (data.options && data.options.length > 0) {
                    let resultsHtml = '';
                    data.options.forEach(option => {
                        resultsHtml += `
                            <div class="idiq-result-item hover:bg-gray-50 p-2 cursor-pointer" 
                                 onclick="selectIdiq('${option.value}', '${option.label}')">
                                <div class="font-medium">${option.label}</div>
                                <div class="text-sm text-gray-500">TAB: ${option.tab_num || 'N/A'}</div>
                            </div>
                        `;
                    });
                    resultsDiv.innerHTML = resultsHtml;
                } else {
                    resultsDiv.innerHTML = '<div class="text-center text-gray-500 py-4">No matches found</div>';
                }
            } else {
                document.getElementById('idiq_search_results').innerHTML = 
                    '<div class="text-center text-red-500 py-4">Error searching for IDIQ contracts</div>';
            }
        })
        .catch(error => {
            console.error('Search error:', error);
            document.getElementById('idiq_search_results').innerHTML = 
                '<div class="text-center text-red-500 py-4">Error connecting to the server</div>';
        });
}

function selectIdiq(id, text) {
    console.log('Selecting IDIQ:', { id, text });
    
    // Update the contract's IDIQ
    fetch(`/processing/match-idiq/${processContractId}/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
        },
        body: JSON.stringify({ 
            idiq_id: id,
            contract_number: text
        })
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(data => {
                throw new Error(data.error || 'Failed to select IDIQ contract');
            }).catch(() => {
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
            alert(data.error || 'Error selecting IDIQ contract');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert(error.message || 'Error selecting IDIQ contract');
    });
}

function removeIdiq() {
    console.log('Removing IDIQ contract');
    
    fetch(`/processing/match-idiq/${processContractId}/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
        },
        body: JSON.stringify({ id: null })
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
            alert(data.error || 'Error removing IDIQ contract');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Error removing IDIQ contract: ' + error.message);
    });
}

// Add event listeners when the document is loaded
document.addEventListener('DOMContentLoaded', function() {
    // Handle IDIQ modal
    document.querySelectorAll('[data-action="open-idiq"]').forEach(button => {
        button.addEventListener('click', function() {
            const idiq = this.dataset.idiq;
            openIdiqModal(idiq);
        });
    });

    // Add event listeners for IDIQ search
    const idiqSearchInput = document.getElementById('idiq_search');
    const idiqSearchButton = document.querySelector('button[onclick="searchIdiq()"]');
    
    if (idiqSearchInput) {
        idiqSearchInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                searchIdiq();
            }
        });
    }
    
    if (idiqSearchButton) {
        idiqSearchButton.addEventListener('click', searchIdiq);
    }
});
