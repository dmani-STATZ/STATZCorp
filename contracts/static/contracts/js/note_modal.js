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

    let currentEntityType = '';
    let currentContractNumber = '';
    let currentClinItemNumber = '';
    
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
            if (typeof window.noteModalApplyAddLayout === 'function') {
                window.noteModalApplyAddLayout();
            }
            
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

            // Capture context for reminder title defaulting
            currentEntityType = (this.dataset.entityType || '').toLowerCase();
            currentContractNumber = this.dataset.contractNumber
                || window.contractNumberForReminders
                || '';
            currentClinItemNumber = this.dataset.itemNumber
                || window.selectedClinItemNumber
                || '';
            
            // Show modal
            noteModal.classList.remove('hidden');
        });
    });
    
    createReminderCheckbox.addEventListener('change', function() {
        if (this.checked) {
            reminderFields.classList.remove('hidden');
            const titleInput = document.getElementById('id_reminder_title');
            if (titleInput && !titleInput.value.trim()) {
                const isClinNote = currentEntityType === 'clin'
                    || currentEntityType.includes('clin');
                const contractNum = currentContractNumber;
                const clinNum = (currentClinItemNumber || '').trim();
                let defaultTitle = contractNum;
                if (isClinNote && clinNum) {
                    defaultTitle = [contractNum, clinNum].filter(Boolean).join('-');
                }
                if (defaultTitle) titleInput.value = defaultTitle;
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
        const contentTypeId = noteContentTypeId ? noteContentTypeId.value : '';
        const objectId = noteObjectId ? noteObjectId.value : '';
        const isEdit = noteForm.dataset.isEdit === '1' || /\/note\/update\/\d+\/$/.test(noteForm.action);

        if (noteForm.dataset.canEdit === '0') {
            window.notify('error', 'This note is read-only.', 5000);
            return;
        }

        const noteField = document.getElementById('id_note');
        const additionField = document.getElementById('id_note_addition');
        if (!noteField) {
            window.notify('error', 'Note field not found.', 5000);
            return;
        }

        if (isEdit) {
            const hadReminderInitially = noteForm.dataset.initialReminderExists === '1';
            const canManageReminderPre = noteForm.dataset.canManageReminder !== '0';
            const reminderCheckedPre = canManageReminderPre && createReminderCheckbox.checked;
            if (canManageReminderPre && hadReminderInitially && !reminderCheckedPre) {
                if (!confirm('This will delete the reminder. Are you sure?')) {
                    return;
                }
            }
        }

        let finalNoteBody;
        if (isEdit) {
            const addTrim = additionField ? (additionField.value || '').trim() : '';
            if (addTrim.length > 0) {
                finalNoteBody = `${formatNoteTimestamp()}\n${additionField.value.trim()}\n\n${noteField.value}`;
            } else {
                finalNoteBody = noteField.value;
            }
            if (additionField) {
                additionField.value = '';
            }
        } else {
            const trimmed = (noteField.value || '').trim();
            if (!trimmed) {
                window.notify('error', 'Please enter a note.', 5000);
                return;
            }
            finalNoteBody = `${formatNoteTimestamp()}\n${trimmed}`;
        }
        noteField.value = finalNoteBody;

        const formData = new FormData(noteForm);
        const noteText = formData.get('note');

        // Validate note text after transforms
        if (!noteText || String(noteText).trim() === '') {
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
                noteText: String(noteText || '')
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
            // Reminder body mirrors final note text (after timestamp / addition merge)
            formData.set('reminder_text', String(noteText || ''));
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
                            if (typeof window.dedupeNoteFullViewModals === 'function') {
                                window.dedupeNoteFullViewModals();
                            }
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
        currentEntityType = '';
        currentContractNumber = '';
        currentClinItemNumber = '';
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
        if (typeof window.noteModalApplyAddLayout === 'function') {
            window.noteModalApplyAddLayout();
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

/**
 * Local timestamp line prepended/appended to note bodies from the modal.
 * Format: --- MM/DD/YYYY HH:MM AM/PM ---
 */
function formatNoteTimestamp() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const month = pad(d.getMonth() + 1);
    const day = pad(d.getDate());
    const year = d.getFullYear();
    let hours = d.getHours();
    const ampm = hours >= 12 ? 'PM' : 'AM';
    hours = hours % 12;
    if (hours === 0) {
        hours = 12;
    }
    const minutes = pad(d.getMinutes());
    return `--- ${month}/${day}/${year} ${hours}:${minutes} ${ampm} ---`;
}

window.noteModalApplyAddLayout = function() {
    const wrap = document.getElementById('noteAdditionWrap');
    const lblAdd = document.getElementById('label_id_note_addition');
    const lblNote = document.getElementById('label_id_note');
    const addTa = document.getElementById('id_note_addition');
    if (wrap) {
        wrap.classList.add('d-none');
    }
    if (lblAdd) {
        lblAdd.textContent = 'Add to Note';
    }
    if (lblNote) {
        lblNote.textContent = 'Note Details';
    }
    if (addTa) {
        addTa.value = '';
    }
};

/**
 * @param {boolean} canEdit - when false, hide the "addition" box (read-only note)
 */
window.noteModalApplyEditLayout = function(canEdit) {
    const wrap = document.getElementById('noteAdditionWrap');
    const lblAdd = document.getElementById('label_id_note_addition');
    const lblNote = document.getElementById('label_id_note');
    const addTa = document.getElementById('id_note_addition');
    if (!canEdit) {
        window.noteModalApplyAddLayout();
        if (wrap) {
            wrap.classList.add('d-none');
        }
        if (lblNote) {
            lblNote.textContent = 'Note Details';
        }
        return;
    }
    if (wrap) {
        wrap.classList.remove('d-none');
    }
    if (lblAdd) {
        lblAdd.textContent = 'Add to Note';
    }
    if (lblNote) {
        lblNote.textContent = 'Existing Note';
    }
    if (addTa) {
        addTa.value = '';
    }
}; 