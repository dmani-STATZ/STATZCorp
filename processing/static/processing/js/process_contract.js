// Utility function to show messages
function showMessage(message, type = 'info') {
    const messageDiv = document.getElementById('message-div') || createMessageDiv();
    messageDiv.className = `fixed top-4 right-4 p-4 rounded-lg shadow-lg ${getMessageClass(type)}`;
    messageDiv.textContent = message;
    messageDiv.style.display = 'block';
    
    // Auto-hide after 5 seconds unless it's an error
    if (type !== 'error') {
        setTimeout(() => {
            messageDiv.style.display = 'none';
        }, 5000);
    }
}

function getMessageClass(type) {
    switch(type) {
        case 'success':
            return 'bg-green-100 text-green-800 border border-green-300';
        case 'error':
            return 'bg-red-100 text-red-800 border border-red-300';
        case 'warning':
            return 'bg-yellow-100 text-yellow-800 border border-yellow-300';
        default:
            return 'bg-blue-100 text-blue-800 border border-blue-300';
    }
}

function createMessageDiv() {
    const div = document.createElement('div');
    div.id = 'message-div';
    div.style.zIndex = '9999';
    document.body.appendChild(div);
    return div;
}

function showValidationErrors(errors) {
    // Clear any existing validation errors first
    clearValidationErrors();
    
    // Handle contract-level errors
    Object.entries(errors).forEach(([field, error]) => {
        if (field === 'clins') {
            // Handle CLIN-specific errors
            errors[field].forEach(clinError => {
                const clinNumber = clinError.clin_number;
                delete clinError.clin_number;
                
                Object.entries(clinError).forEach(([clinField, clinFieldError]) => {
                    const fieldId = `clin-${clinNumber}-${clinField}`;
                    const element = document.getElementById(fieldId);
                    if (element) {
                        element.classList.add('border-red-500');
                        
                        // Add error message below the field
                        const errorDiv = document.createElement('div');
                        errorDiv.className = 'text-red-500 text-sm mt-1 validation-error';
                        errorDiv.textContent = clinFieldError;
                        element.parentNode.appendChild(errorDiv);
                    }
                });
            });
        } else {
            // Handle contract-level field errors
            const element = document.getElementById(field);
            if (element) {
                element.classList.add('border-red-500');
                
                // Add error message below the field
                const errorDiv = document.createElement('div');
                errorDiv.className = 'text-red-500 text-sm mt-1 validation-error';
                errorDiv.textContent = error;
                element.parentNode.appendChild(errorDiv);
            }
        }
    });
    
    // Show a summary message at the top
    showMessage('Please correct the highlighted fields before finalizing', 'error');
}

function clearValidationErrors() {
    // Remove all validation error styles
    document.querySelectorAll('.border-red-500').forEach(element => {
        element.classList.remove('border-red-500');
    });
    
    // Remove all validation error messages
    document.querySelectorAll('.validation-error').forEach(element => {
        element.remove();
    });
}

async function finalizeContract() {
    try {
        if (!confirm('Are you sure you want to finalize this contract? This action cannot be undone.')) {
            return;
        }

        // Clear any existing validation errors
        clearValidationErrors();
        
        // Show saving indicator
        showMessage('Saving final changes...', 'info');
        
        // Get the form and its data
        const form = document.querySelector('form');
        const formData = new FormData(form);
        
        // Save any pending changes first
        const saveResponse = await fetch(form.action, {
            method: 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
            }
        });

        if (!saveResponse.ok) {
            const saveData = await saveResponse.json();
            if (saveData.validation_errors) {
                showValidationErrors(saveData.validation_errors);
                return;
            }
            throw new Error(saveData.error || 'Failed to save changes');
        }

        // Now finalize the contract
        showMessage('Finalizing contract...', 'info');
        
        const processContractId = document.getElementById('process_contract_id').value;
        const response = await fetch(`/processing/contract/${processContractId}/finalize-and-email/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
                'Content-Type': 'application/json'
            }
        });

        const data = await response.json();

        if (!response.ok) {
            if (data.validation_errors) {
                showValidationErrors(data.validation_errors);
                return;
            }
            throw new Error(data.error || 'Failed to finalize contract');
        }

        if (data.success) {
            showMessage('Contract finalized successfully', 'success');
            
            // Open email client with pre-populated email
            if (data.mailto_url) {
                window.location.href = data.mailto_url;
            }
            
            // Redirect to queue after a short delay
            setTimeout(() => {
                window.location.href = "/processing/queue/";
            }, 2000);
        } else {
            throw new Error(data.error || 'Failed to finalize contract');
        }
    } catch (error) {
        console.error('Error finalizing contract:', error);
        showMessage(`Error finalizing contract: ${error.message}`, 'error');
    }
}

// Update CSS for alerts
const style = document.createElement('style');
style.textContent = `
    .error-field {
        border: 2px solid red !important;
        background-color: #fff3f3 !important;
    }
    
    .alert {
        padding: 1rem;
        margin-bottom: 1rem;
        border: 1px solid transparent;
        border-radius: 0.25rem;
        position: relative;
    }
    
    .alert-danger {
        color: #721c24;
        background-color: #f8d7da;
        border-color: #f5c6cb;
    }

    .alert-info {
        color: #0c5460;
        background-color: #d1ecf1;
        border-color: #bee5eb;
    }

    .close {
        position: absolute;
        right: 10px;
        top: 10px;
        padding: 0;
        background: transparent;
        border: 0;
        font-size: 1.5rem;
        font-weight: 700;
        line-height: 1;
        color: inherit;
        opacity: .5;
        cursor: pointer;
    }

    .close:hover {
        opacity: .75;
    }
`;
document.head.appendChild(style); 