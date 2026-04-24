/**
 * Note Modal Functionality
 * 
 * This script handles the functionality for the note modal dialog
 * that can be used across different pages to add notes to various entities
 * (IDIQ, Contract, CLIN) with optional reminder functionality.
 */

document.addEventListener('DOMContentLoaded', function() {
    // console.log('DOM loaded, initializing note modal functionality');
    
    // Get CSRF token
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    const csrftoken = getCookie('csrftoken');
    if (!csrftoken) {
        console.error('CSRF token not found in cookies');
        return;
    }

    // Set up CSRF token for all fetch requests
    function fetchWithCSRF(url, options = {}) {
        if (!options.headers) {
            options.headers = {};
        }
        options.headers['X-CSRFToken'] = csrftoken;
        return fetch(url, options);
    }

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
    const reminderSection = createReminderCheckbox
        ? createReminderCheckbox.closest('.mt-6')
        : null;
    
    // Check if buttons exist
    if (!closeNoteModalBtn) console.error('closeNoteModalBtn element not found');
    if (!cancelNoteModalBtn) console.error('cancelNoteModalBtn element not found');
    if (!saveNoteBtn) console.error('saveNoteBtn element not found');
    if (!noteModalBackdrop) console.error('noteModalBackdrop element not found');
    
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
                window.notify('error', 'Configuration error. Please contact the administrator.', 5000);
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
                referringUrlField.value = window.location.pathname;
                // console.log('Set referring URL:', referringUrlField.value);
            }
            
            // Reset form
            noteForm.reset();
            createReminderCheckbox.checked = false;
            reminderFields.classList.add('hidden');
            
            // Set form action for add
            noteForm.action = `/contracts/note/add/${contentTypeId}/${objectId}/`;
            noteForm.method = 'POST';
            noteForm.dataset.isEdit = '0';
            noteForm.dataset.initialReminderExists = '0';
            noteForm.dataset.canEdit = '1';
            noteForm.dataset.canManageReminder = '1';
            noteForm.dataset.initialReminderSnapshot = '';
            
            // Re-set the hidden fields after form reset
            noteContentTypeId.value = contentTypeId;
            noteObjectId.value = objectId;
            if (referringUrlField) {
                referringUrlField.value = window.location.pathname;
            }
            
            // Show modal
            noteModal.classList.remove('hidden');
        });
    });
    
    // Toggle reminder fields visibility; default Reminder Title when the checkbox is turned on
    createReminderCheckbox.addEventListener('change', function() {
        if (this.checked) {
            reminderFields.classList.remove('hidden');
            const titleInput = document.getElementById('id_reminder_title');
            if (titleInput && !titleInput.value.trim()) {
                const t = (noteModalTitle && noteModalTitle.textContent) || '';
                const isClinNote = t.toLowerCase().includes('clin');
                const contractNum = window.contractNumberForReminders || '';
                const clinNum = (window.selectedClinItemNumber || '').trim();
                let defaultTitle = contractNum;
                if (isClinNote && clinNum) {
                    const parts = [contractNum, clinNum].filter(Boolean);
                    defaultTitle = parts.join('-');
                }
                if (defaultTitle) {
                    titleInput.value = defaultTitle;
                }
            }
        } else {
            reminderFields.classList.add('hidden');
        }
    });
    
    // Close modal when clicking close button
    closeNoteModalBtn.addEventListener('click', closeModal);
    cancelNoteModalBtn.addEventListener('click', closeModal);
    noteModalBackdrop.addEventListener('click', closeModal);
    
    // Handle form submission
    saveNoteBtn.addEventListener('click', async function() {
        // console.log('Save Note button clicked');
        
        // Get form data
        const formData = new FormData(noteForm);
        const noteText = formData.get('note');
        const contentTypeId = formData.get('content_type_id');
        const objectId = formData.get('object_id');
        const isEdit = noteForm.dataset.isEdit === '1' || /\/note\/update\/\d+\/$/.test(noteForm.action);

        if (noteForm.dataset.canEdit === '0') {
            window.notify('error', 'This note is read-only.', 5000);
            return;
        }
        
        // Validate note text
        if (!noteText || noteText.trim() === '') {
            window.notify('error', 'Please enter a note.', 5000);
            return;
        }
        
        // Validate required fields
        if (!contentTypeId || !objectId) {
            window.notify('error', 'Missing required fields. Please try again or contact support.', 5000);
            console.error('Missing required fields:', { contentTypeId, objectId });
            return;
        }

        if (!isEdit) {
            // Force add-note endpoint for add mode.
            noteForm.action = `/contracts/note/add/${contentTypeId}/${objectId}/`;
        }

        if (isEdit) {
            const hadReminderInitially = noteForm.dataset.initialReminderExists === '1';
            const canManageReminder = noteForm.dataset.canManageReminder !== '0';
            const reminderChecked = canManageReminder && createReminderCheckbox.checked;
            let reminderAction = 'none';
            let initialReminderSnapshot = null;

            if (noteForm.dataset.initialReminderSnapshot) {
                try {
                    initialReminderSnapshot = JSON.parse(noteForm.dataset.initialReminderSnapshot);
                } catch (e) {
                    initialReminderSnapshot = null;
                }
            }

            const currentReminderSnapshot = {
                reminderTitle: formData.get('reminder_title') || '',
                reminderDate: formData.get('reminder_date') || '',
                reminderCompleted: formData.get('reminder_completed') === 'on',
                noteText: (formData.get('note') || '')
            };

            const reminderChanged = initialReminderSnapshot
                ? (
                    (initialReminderSnapshot.reminderTitle || '') !== currentReminderSnapshot.reminderTitle ||
                    (initialReminderSnapshot.reminderDate || '') !== currentReminderSnapshot.reminderDate ||
                    !!initialReminderSnapshot.reminderCompleted !== currentReminderSnapshot.reminderCompleted ||
                    (initialReminderSnapshot.noteText || '') !== currentReminderSnapshot.noteText
                )
                : true;

            if (canManageReminder) {
                if (hadReminderInitially && !reminderChecked) {
                    if (!confirm('This will delete the reminder. Are you sure?')) {
                        return;
                    }
                    reminderAction = 'delete';
                } else if (reminderChecked && !hadReminderInitially) {
                    reminderAction = 'create';
                } else if (reminderChecked && hadReminderInitially && reminderChanged) {
                    reminderAction = 'update';
                }
            }

            formData.append('reminder_action', reminderAction);
        }
        
        // Validate reminder fields if reminder is checked
        const canManageReminder = noteForm.dataset.canManageReminder !== '0';
        if (canManageReminder && createReminderCheckbox.checked) {
            const reminderTitle = formData.get('reminder_title');
            const reminderDate = formData.get('reminder_date');
            
            if (!reminderTitle || reminderTitle.trim() === '') {
                window.notify('error', 'Please enter a reminder title.', 5000);
                return;
            }
            
            if (!reminderDate) {
                window.notify('error', 'Please select a reminder date.', 5000);
                return;
            }
            // Reminder body mirrors note text (separate Reminder Details field removed)
            const noteTextForReminder = (formData.get('note') || '');
            formData.set('reminder_text', noteTextForReminder);
        }
        
        // Show loading state
        saveNoteBtn.disabled = true;
        saveNoteBtn.textContent = 'Saving...';
        
        try {
            // Submit form
            const response = await fetch(noteForm.action, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrftoken,
                    'X-Requested-With': 'XMLHttpRequest'  // Add this to indicate AJAX request
                },
                body: formData
            });
            
            // Check if we got a redirect
            if (response.redirected) {
                window.location.href = response.url;
                return;
            }
            
            // Try to parse as JSON, but don't throw if it's not JSON
            let data;
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                data = await response.json();
                if (data.success) {
                    window.notify('success', 'Note added successfully.', 3000);
                    closeModal();
                    let refreshed = false;

                    if (data.notes_html) {
                        const isContract = String(contentTypeId) === String(window.contractContentTypeId);
                        const notesPanel = isContract
                            ? document.getElementById('notes-panel-contract')
                            : document.getElementById('notes-panel-clin');
                        if (notesPanel) {
                            notesPanel.innerHTML = data.notes_html;
                            if (typeof window.setupEditButtons === 'function') {
                                window.setupEditButtons(notesPanel);
                            }
                            refreshed = true;
                        }
                    }

                    if (!refreshed && typeof window.refreshCurrentNotesPanel === 'function') {
                        window.refreshCurrentNotesPanel();
                        refreshed = true;
                    }

                    if (!refreshed) {
                        window.location.reload();
                    }
                } else {
                    throw new Error(data.error || 'Failed to add note');
                }
            } else {
                // If not JSON, fall back to reload.
                window.location.reload();
            }
        } catch (error) {
            console.error('Error saving note:', error);
            window.notify('error', error.message || 'Failed to save note. Please try again.', 5000);
        } finally {
            // Reset button state
            saveNoteBtn.disabled = false;
            saveNoteBtn.textContent = 'Save Note';
        }
    });
    
    // Function to close the modal
    function closeModal() {
        noteModal.classList.add('hidden');
        // Reset form state
        saveNoteBtn.disabled = false;
        saveNoteBtn.textContent = 'Save Note';
        noteForm.dataset.isEdit = '0';
        noteForm.dataset.initialReminderExists = '0';
        noteForm.dataset.canEdit = '1';
        noteForm.dataset.canManageReminder = '1';
        noteForm.dataset.initialReminderSnapshot = '';
        const noteTextArea = document.getElementById('id_note');
        if (noteTextArea) {
            noteTextArea.readOnly = false;
        }
        if (saveNoteBtn) {
            saveNoteBtn.style.display = '';
        }
        if (reminderSection) {
            reminderSection.classList.remove('hidden');
        }
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