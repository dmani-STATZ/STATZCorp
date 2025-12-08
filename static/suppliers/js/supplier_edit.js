// Wrap everything in an IIFE to prevent global namespace pollution and duplicate declarations
(function() {
    'use strict';
    
    // Track original form values for change detection
    let originalValues = {};
    let changedFields = new Set();
    const DEBUG = true; // Set to false to disable console logging

    function log(...args) {
        if (DEBUG) {
            console.log('[SupplierEdit]', ...args);
        }
    }

    // Test that script is loading
    console.log('✅ supplier_edit.js loaded successfully v20251204-001');

document.addEventListener('DOMContentLoaded', () => {
    log('🚀 Initializing supplier edit form...');
    
    // Verify we're on the right page
    const form = document.querySelector('form');
    if (!form) {
        console.error('❌ CRITICAL: No form found on page!');
        return;
    }
    log('✅ Form found');
    
    initAddressPickers();
    captureOriginalValues();
    initChangeTracking();
    addPendingChangesIndicator();
    initFormSubmission();
    
    log('✅ Initialization complete. Original values:', originalValues);
    log(`📊 Tracking ${Object.keys(originalValues).length} form fields`);
    
    // Add a temporary visual indicator to confirm JS is working
    showInitializationSuccess();
});

function showInitializationSuccess() {
    // Create a temporary notification
    const notification = document.createElement('div');
    notification.id = 'change-tracker-notification';
    notification.style.cssText = `
        position: fixed;
        top: 80px;
        right: 20px;
        background: #10b981;
        color: white;
        padding: 12px 20px;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        z-index: 9999;
        font-size: 14px;
        font-weight: 500;
        animation: slideIn 0.3s ease-out;
    `;
    notification.innerHTML = `
        <div style="display: flex; align-items: center; gap: 8px;">
            <svg style="width: 20px; height: 20px;" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
            </svg>
            <span>Change Tracking Active</span>
        </div>
    `;
    
    // Add animation
    const style = document.createElement('style');
    style.textContent = `
        @keyframes slideIn {
            from {
                transform: translateX(400px);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }
        @keyframes slideOut {
            from {
                transform: translateX(0);
                opacity: 1;
            }
            to {
                transform: translateX(400px);
                opacity: 0;
            }
        }
    `;
    document.head.appendChild(style);
    document.body.appendChild(notification);
    
    // Remove after 3 seconds
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease-out';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

function captureOriginalValues() {
    const form = document.querySelector('form');
    if (!form) {
        log('ERROR: Form not found!');
        return;
    }

    // Capture all form field values
    const formElements = form.querySelectorAll('input, select, textarea');
    log(`Found ${formElements.length} form elements`);
    
    formElements.forEach(element => {
        if (element.type === 'checkbox') {
            originalValues[element.id] = element.checked;
            log(`Checkbox ${element.id} (${element.name}): ${element.checked}`);
        } else if (element.type !== 'hidden' || element.name.includes('address')) {
            originalValues[element.id] = element.value;
            if (element.name && !element.name.includes('csrf')) {
                log(`Field ${element.id} (${element.name}): "${element.value}"`);
            }
        }
    });
}

function markFieldAsChanged(fieldId, fieldElement) {
    changedFields.add(fieldId);
    
    // Find the field container - for checkboxes, look for toggle-control parent
    let container = null;
    
    // Check if this is a checkbox within a toggle control
    if (fieldElement.type === 'checkbox') {
        const toggleControl = document.querySelector(`.toggle-control[data-checkbox-id="${fieldId}"]`);
        if (toggleControl) {
            container = toggleControl.closest('.flex.items-center.justify-between');
        }
    }
    
    // If not found, try other containers
    if (!container) {
        container = fieldElement.closest('div[id]') || 
                    fieldElement.closest('.form-group') || 
                    fieldElement.closest('.border');
    }
    
    if (!container) {
        // For simple fields, find parent div
        container = fieldElement.parentElement;
        while (container && !container.classList.contains('grid')) {
            if (container.querySelector('label') || container.classList.contains('border')) {
                break;
            }
            container = container.parentElement;
        }
    }
    
    if (container && !container.querySelector('.change-indicator')) {
        // Add visual indicator
        const indicator = document.createElement('div');
        indicator.className = 'change-indicator';
        indicator.title = 'Pending change';
        
        // Make container relative if not already
        const position = window.getComputedStyle(container).position;
        if (position === 'static') {
            container.style.position = 'relative';
        }
        
        container.appendChild(indicator);
        
        // Add border highlight to input fields
        if (fieldElement.classList.contains('form-input') || 
            fieldElement.classList.contains('form-select') ||
            fieldElement.tagName === 'SELECT') {
            fieldElement.classList.add('border-amber-400', 'border-2');
            fieldElement.classList.remove('border-gray-300');
        }
        
        // Add highlight to toggle controls
        if (fieldElement.type === 'checkbox') {
            const toggleControl = document.querySelector(`.toggle-control[data-checkbox-id="${fieldId}"]`);
            if (toggleControl) {
                toggleControl.classList.add('ring-2', 'ring-amber-400', 'ring-offset-1');
            }
        }
    }
    
    updatePendingChangesCounter();
}

function clearFieldChangeIndicator(fieldId, fieldElement) {
    changedFields.delete(fieldId);
    
    // Find the field container - for checkboxes, look for toggle-control parent
    let container = null;
    
    if (fieldElement.type === 'checkbox') {
        const toggleControl = document.querySelector(`.toggle-control[data-checkbox-id="${fieldId}"]`);
        if (toggleControl) {
            container = toggleControl.closest('.flex.items-center.justify-between');
        }
    }
    
    if (!container) {
        container = fieldElement.closest('div[id]') || 
                    fieldElement.closest('.form-group') || 
                    fieldElement.closest('.border');
    }
    
    if (!container) {
        container = fieldElement.parentElement;
        while (container && !container.classList.contains('grid')) {
            if (container.querySelector('label') || container.classList.contains('border')) {
                break;
            }
            container = container.parentElement;
        }
    }
    
    if (container) {
        const indicator = container.querySelector('.change-indicator');
        if (indicator) {
            indicator.remove();
        }
        
        // Remove border highlight
        if (fieldElement.classList.contains('form-input') || 
            fieldElement.classList.contains('form-select') ||
            fieldElement.tagName === 'SELECT') {
            fieldElement.classList.remove('border-amber-400', 'border-2');
            fieldElement.classList.add('border-gray-300');
        }
        
        // Remove highlight from toggle controls
        if (fieldElement.type === 'checkbox') {
            const toggleControl = document.querySelector(`.toggle-control[data-checkbox-id="${fieldId}"]`);
            if (toggleControl) {
                toggleControl.classList.remove('ring-2', 'ring-amber-400', 'ring-offset-1');
            }
        }
    }
    
    updatePendingChangesCounter();
}

function initChangeTracking() {
    const form = document.querySelector('form');
    if (!form) {
        log('ERROR: Cannot init change tracking - form not found');
        return;
    }

    log('Initializing change tracking...');

    // Track all input changes
    form.addEventListener('input', (e) => {
        const element = e.target;
        if (!element.id) return;

        const currentValue = element.type === 'checkbox' ? element.checked : element.value;
        const originalValue = originalValues[element.id];
        
        if (currentValue != originalValue) {
            log(`Field changed via input: ${element.name || element.id} (${originalValue} -> ${currentValue})`);
            markFieldAsChanged(element.id, element);
        } else {
            clearFieldChangeIndicator(element.id, element);
        }
    });

    // Track changes from our custom toggle controls and selects
    form.addEventListener('change', (e) => {
        const element = e.target;
        if (!element.id) return;

        const currentValue = element.type === 'checkbox' ? element.checked : element.value;
        const originalValue = originalValues[element.id];
        
        if (currentValue != originalValue) {
            log(`Field changed via change event: ${element.name || element.id} (${originalValue} -> ${currentValue})`);
            markFieldAsChanged(element.id, element);
        } else {
            log(`Field reverted to original: ${element.name || element.id}`);
            clearFieldChangeIndicator(element.id, element);
        }
    });
}

function addPendingChangesIndicator() {
    // Add a counter badge to the save button
    const saveButton = document.querySelector('button[type="submit"]');
    if (!saveButton) return;
    
    const badge = document.createElement('span');
    badge.id = 'pending-changes-badge';
    badge.className = 'hidden ml-2 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-800';
    badge.textContent = '0';
    
    saveButton.appendChild(badge);
}

function updatePendingChangesCounter() {
    const badge = document.getElementById('pending-changes-badge');
    if (!badge) return;
    
    const count = changedFields.size;
    badge.textContent = count;
    
    if (count > 0) {
        badge.classList.remove('hidden');
    } else {
        badge.classList.add('hidden');
    }
}

function initAddressPickers() {
    // Note: This handles the address select dropdowns
    const addressSelects = document.querySelectorAll('select[name$="_address"]');
    
    if (addressSelects.length === 0) {
        log('WARNING: No address select fields found');
        return;
    }
    
    log(`Initializing ${addressSelects.length} address select fields...`);
    
    addressSelects.forEach((select) => {
        // Store initial value
        const initialValue = select.value;
        originalValues[select.id] = initialValue;
        log(`Address field ${select.name}: initial value = ${initialValue}`);
        
        // Note: change tracking is handled by the main change tracking function
    });
}

function initFormSubmission() {
    const form = document.querySelector('form');
    if (!form) return;

    form.addEventListener('submit', (e) => {
        log('Form submitting...');
        log('Changed fields:', Array.from(changedFields));
        
        // Log all checkbox states
        const checkboxes = form.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(cb => {
            log(`Submitting ${cb.name}: ${cb.checked}`);
        });
    });
}

// Close the IIFE
})();
