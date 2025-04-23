/**
 * Note Modal Functionality
 * 
 * This script handles the functionality for the note modal dialog
 * that can be used across different pages to add notes to various entities
 * (IDIQ, Contract, CLIN) with optional reminder functionality.
 */

document.addEventListener('DOMContentLoaded', function() {
    // console.log('DOM loaded, initializing note modal functionality');
    
    // Get modal elements
    const noteModal = document.getElementById('noteModal');
    const noteModalTitle = document.getElementById('noteModalTitle');
    const noteForm = document.getElementById('noteForm');
    const noteContentTypeId = document.getElementById('noteContentTypeId');
    const noteObjectId = document.getElementById('noteObjectId');
    const createReminderCheckbox = document.getElementById('createReminder');
    const reminderFields = document.getElementById('reminderFields');
    
    // Check if elements exist
    if (!noteModal) console.error('noteModal element not found');
    if (!noteModalTitle) console.error('noteModalTitle element not found');
    if (!noteForm) console.error('noteForm element not found');
    if (!noteContentTypeId) console.error('noteContentTypeId element not found');
    if (!noteObjectId) console.error('noteObjectId element not found');
    if (!createReminderCheckbox) console.error('createReminderCheckbox element not found');
    if (!reminderFields) console.error('reminderFields element not found');
    
    // Get buttons
    const closeNoteModalBtn = document.getElementById('closeNoteModal');
    const cancelNoteModalBtn = document.getElementById('cancelNoteModal');
    const saveNoteBtn = document.getElementById('saveNoteBtn');
    const noteModalBackdrop = document.getElementById('noteModalBackdrop');
    
    // Check if buttons exist
    if (!closeNoteModalBtn) console.error('closeNoteModalBtn element not found');
    if (!cancelNoteModalBtn) console.error('cancelNoteModalBtn element not found');
    if (!saveNoteBtn) console.error('saveNoteBtn element not found');
    if (!noteModalBackdrop) console.error('noteModalBackdrop element not found');
    
    // Check for CSRF token
    const csrfForm = document.getElementById('csrf-form');
    if (!csrfForm) console.error('csrf-form element not found');
    
    const csrfToken = csrfForm ? csrfForm.querySelector('[name=csrfmiddlewaretoken]') : null;
    if (!csrfToken) console.error('CSRF token not found');
    else console.log('CSRF token found');
    
    // Find all add note buttons
    const addNoteButtons = document.querySelectorAll('[data-note-action="add"]');
    // console.log(`Found ${addNoteButtons.length} add note buttons`);
    
    // Add event listeners to all "Add Note" buttons with data attributes
    addNoteButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation(); // Prevent event bubbling
            
            // Get data attributes
            const contentTypeId = this.dataset.contentTypeId;
            const objectId = this.dataset.objectId;
            const entityType = this.dataset.entityType || 'Item';
            
            // console.log(`Add Note button clicked:`, {
            //     contentTypeId,
            //     objectId,
            //     entityType
            // });
            
            // Validate required data attributes
            if (!contentTypeId || !objectId) {
                console.error('Missing required data attributes: content-type-id or object-id');
                showErrorMessage('Configuration error. Please contact the administrator.');
                return;
            }
            
            // Set modal title based on entity type
            noteModalTitle.textContent = `Add ${entityType} Note`;
            
            // Set form hidden fields
            noteContentTypeId.value = contentTypeId;
            noteObjectId.value = objectId;
            
            // Set the referring URL
            const referringUrlField = document.getElementById('noteReferringUrl');
            if (referringUrlField) {
                referringUrlField.value = window.location.href;
                // console.log('Set referring URL:', referringUrlField.value);
            }
            
            // Reset form
            noteForm.reset();
            createReminderCheckbox.checked = false;
            reminderFields.classList.add('hidden');
            
            // Set form action for add
            noteForm.action = '/contracts/api/add-note/';
            noteForm.method = 'POST';
            
            // Re-set the hidden fields after form reset
            noteContentTypeId.value = contentTypeId;
            noteObjectId.value = objectId;
            if (referringUrlField) {
                referringUrlField.value = window.location.href;
            }
            
            // Show modal
            noteModal.classList.remove('hidden');
        });
    });
    
    // Toggle reminder fields visibility
    createReminderCheckbox.addEventListener('change', function() {
        if (this.checked) {
            reminderFields.classList.remove('hidden');
        } else {
            reminderFields.classList.add('hidden');
        }
    });
    
    // Close modal when clicking close button
    closeNoteModalBtn.addEventListener('click', closeModal);
    cancelNoteModalBtn.addEventListener('click', closeModal);
    noteModalBackdrop.addEventListener('click', closeModal);
    
    // Handle form submission
    saveNoteBtn.addEventListener('click', function() {
        // console.log('Save Note button clicked');
        
        // Get form data
        const formData = new FormData(noteForm);
        const noteText = formData.get('note');
        const contentTypeId = formData.get('content_type_id');
        const objectId = formData.get('object_id');
        
        // Debug form data
        // console.log('Form data:', {
        //     noteText,
        //     contentTypeId,
        //     objectId,
        //     createReminder: formData.get('create_reminder')
        // });
        
        // Validate note text
        if (!noteText || noteText.trim() === '') {
            showErrorMessage('Please enter a note.');
            return;
        }
        
        // Validate required fields
        if (!contentTypeId || !objectId) {
            showErrorMessage('Missing required fields. Please try again or contact support.');
            console.error('Missing required fields:', { contentTypeId, objectId });
            return;
        }
        
        // Validate reminder fields if reminder is checked
        if (createReminderCheckbox.checked) {
            const reminderTitle = formData.get('reminder_title');
            const reminderDate = formData.get('reminder_date');
            
            if (!reminderTitle || reminderTitle.trim() === '') {
                showErrorMessage('Please enter a reminder title.');
                return;
            }
            
            if (!reminderDate) {
                showErrorMessage('Please select a reminder date.');
                return;
            }
        }
        
        // Show loading state
        saveNoteBtn.disabled = true;
        saveNoteBtn.textContent = 'Saving...';
        
        // Get CSRF token
        const csrfForm = document.getElementById('csrf-form');
        const csrfToken = csrfForm ? csrfForm.querySelector('[name=csrfmiddlewaretoken]').value : '';
        
        if (!csrfToken) {
            console.error('CSRF token not found');
            showErrorMessage('CSRF token not found. Please refresh the page and try again.');
            saveNoteBtn.disabled = false;
            saveNoteBtn.textContent = 'Save Note';
            return;
        }
        
        // console.log('CSRF token:', csrfToken ? 'Found' : 'Not found');
        
        // Submit form
        noteForm.submit();
    });
    
    // Function to close the modal
    function closeModal() {
        noteModal.classList.add('hidden');
        // Reset form state
        saveNoteBtn.disabled = false;
        saveNoteBtn.textContent = 'Save Note';
    }
    
    // Function to show error message
    function showErrorMessage(message) {
        // Create an error message element
        const errorMessage = document.createElement('div');
        errorMessage.className = 'fixed top-4 right-4 bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded z-50 shadow-md';
        errorMessage.innerHTML = `
            <div class="flex items-center">
                <svg class="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span>${message}</span>
            </div>
        `;
        
        // Add to the document
        document.body.appendChild(errorMessage);
        
        // Remove after 5 seconds
        setTimeout(() => {
            errorMessage.classList.add('opacity-0', 'transition-opacity', 'duration-500');
            setTimeout(() => {
                document.body.removeChild(errorMessage);
            }, 500);
        }, 5000);
    }
    
    // Function to show success message
    function showSuccessMessage(message) {
        // Create a success message element
        const successMessage = document.createElement('div');
        successMessage.className = 'fixed top-4 right-4 bg-green-100 border border-green-400 text-green-700 px-4 py-3 rounded z-50 shadow-md';
        successMessage.innerHTML = `
            <div class="flex items-center">
                <svg class="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                </svg>
                <span>${message}</span>
            </div>
        `;
        
        // Add to the document
        document.body.appendChild(successMessage);
        
        // Remove after 3 seconds
        setTimeout(() => {
            successMessage.classList.add('opacity-0', 'transition-opacity', 'duration-500');
            setTimeout(() => {
                document.body.removeChild(successMessage);
            }, 500);
        }, 3000);
    }
    
    // Close modal when pressing Escape key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && !noteModal.classList.contains('hidden')) {
            closeModal();
        }
    });
    
    // Make the closeModal function globally available
    window.closeNoteModal = closeModal;
}); 