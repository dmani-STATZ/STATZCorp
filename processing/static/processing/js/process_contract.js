// Utility function to show messages
function showMessage(message, type = 'info') {
    const container = document.getElementById('toast-container') || createToastContainer();
    const toast = document.createElement('div');
    toast.className = `toast ${getMessageClass(type)}`;

    const messageBlock = document.createElement('pre');
    messageBlock.className = 'toast-message';
    messageBlock.textContent = message;

    const actions = document.createElement('div');
    actions.className = 'toast-actions';

    const copyButton = document.createElement('button');
    copyButton.type = 'button';
    copyButton.className = 'toast-action';
    copyButton.textContent = 'Copy';
    copyButton.addEventListener('click', () => {
        navigator.clipboard.writeText(message).then(() => {
            copyButton.textContent = 'Copied!';
            setTimeout(() => (copyButton.textContent = 'Copy'), 1500);
        }).catch(() => {
            copyButton.textContent = 'Failed';
            setTimeout(() => (copyButton.textContent = 'Copy'), 1500);
        });
    });

    const closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'toast-close';
    closeButton.setAttribute('aria-label', 'Dismiss message');
    closeButton.innerHTML = '&times;';
    closeButton.addEventListener('click', () => dismissToast(toast));

    actions.appendChild(copyButton);
    actions.appendChild(closeButton);

    toast.appendChild(messageBlock);
    toast.appendChild(actions);
    container.appendChild(toast);

    if (type !== 'error') {
        setTimeout(() => dismissToast(toast), 6000);
    }
}

function createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
    return container;
}

function dismissToast(toast) {
    if (!toast) return;
    toast.classList.add('toast-hide');
    toast.addEventListener('animationend', () => {
        if (toast.parentNode) {
            toast.parentNode.removeChild(toast);
        }
    }, { once: true });
}

function getMessageClass(type) {
    switch (type) {
        case 'success':
            return 'toast-success';
        case 'error':
            return 'toast-error';
        case 'warning':
            return 'toast-warning';
        default:
            return 'toast-info';
    }
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
    #toast-container {
        position: fixed;
        top: 1rem;
        right: 1rem;
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
        z-index: 9999;
        max-width: min(480px, 90vw);
    }

    .toast {
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
        padding: 1rem 1.25rem;
        border-radius: 0.75rem;
        box-shadow: 0 10px 25px rgba(15, 23, 42, 0.18);
        border: 1px solid transparent;
        animation: toast-in 0.2s ease-out;
        backdrop-filter: blur(8px);
    }

    .toast-hide {
        animation: toast-out 0.2s ease-in forwards;
    }

    @keyframes toast-in {
        from {
            opacity: 0;
            transform: translateY(-10px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }

    @keyframes toast-out {
        from {
            opacity: 1;
            transform: translateY(0);
        }
        to {
            opacity: 0;
            transform: translateY(-10px);
        }
    }

    .toast-message {
        margin: 0;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
        font-size: 0.875rem;
        line-height: 1.5;
        white-space: pre-wrap;
        word-break: break-word;
    }

    .toast-actions {
        display: flex;
        justify-content: flex-end;
        gap: 0.5rem;
    }

    .toast-action {
        background: rgba(255, 255, 255, 0.65);
        border: 1px solid rgba(255, 255, 255, 0.7);
        color: inherit;
        padding: 0.35rem 0.75rem;
        border-radius: 0.5rem;
        font-size: 0.75rem;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.15s ease, transform 0.15s ease;
    }

    .toast-action:hover {
        background: rgba(255, 255, 255, 0.85);
        transform: translateY(-1px);
    }

    .toast-close {
        background: transparent;
        border: none;
        color: inherit;
        font-size: 1.25rem;
        line-height: 1;
        cursor: pointer;
        padding: 0.25rem;
        margin-left: 0.25rem;
    }

    .toast-success {
        background: rgba(22, 163, 74, 0.1);
        border-color: rgba(22, 163, 74, 0.25);
        color: #14532d;
    }

    .toast-error {
        background: rgba(220, 38, 38, 0.1);
        border-color: rgba(220, 38, 38, 0.25);
        color: #7f1d1d;
    }

    .toast-warning {
        background: rgba(234, 179, 8, 0.12);
        border-color: rgba(234, 179, 8, 0.28);
        color: #713f12;
    }

    .toast-info {
        background: rgba(59, 130, 246, 0.12);
        border-color: rgba(59, 130, 246, 0.28);
        color: #1e3a8a;
    }

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
