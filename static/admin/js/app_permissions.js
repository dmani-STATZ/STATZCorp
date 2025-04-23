// Wait for DOM content to load
document.addEventListener('DOMContentLoaded', function() {
    console.log('App permissions JS loaded');
    
    // Check if we're on the right page
    const isAddPage = window.location.href.includes('/add/');
    const isChangePage = window.location.href.includes('/change/');
    console.log('Is add page:', isAddPage);
    console.log('Is change page:', isChangePage);
    
    // Try different possible IDs for the user select element
    const possibleUserSelectors = ['#id_user', 'select[name="user"]', '#user', 'select'];
    let userSelect = null;
    
    // Try to find the user select element
    for (const selector of possibleUserSelectors) {
        const element = document.querySelector(selector);
        if (element) {
            console.log('Found user select with selector:', selector);
            userSelect = element;
            break;
        } else {
            console.log('Selector not found:', selector);
        }
    }
    
    // Debug all selects on the page
    const allSelects = document.querySelectorAll('select');
    console.log('All select elements on page:', allSelects.length);
    allSelects.forEach((select, index) => {
        console.log(`Select ${index}:`, select.id, select.name);
    });
    
    if (userSelect) {
        console.log('User select found:', userSelect.value);
        
        // Function to load permissions for a user
        function loadPermissionsForUser(userId) {
            console.log('Loading permissions for user ID:', userId);
            
            // Debug all checkboxes on the page
            const allCheckboxes = document.querySelectorAll('input[type="checkbox"]');
            console.log('All checkboxes on page:', allCheckboxes.length);
            allCheckboxes.forEach((checkbox, index) => {
                console.log(`Checkbox ${index}:`, checkbox.id, checkbox.name);
            });
            
            // Clear all checkboxes first
            document.querySelectorAll('input[type="checkbox"][id^="id_app_"]').forEach(checkbox => {
                checkbox.checked = false;
                console.log('Reset checkbox:', checkbox.id);
            });
            
            // Fetch permissions for selected user
            fetch(`/admin/users/apppermission/get-permissions/?user_id=${userId}`)
                .then(response => {
                    console.log('API response status:', response.status);
                    if (!response.ok) {
                        throw new Error('Network response was not ok');
                    }
                    return response.json();
                })
                .then(data => {
                    console.log('Permissions loaded:', data);
                    console.log('Permission keys:', Object.keys(data));
                    
                    // If no permissions found, just reset checkboxes
                    if (Object.keys(data).length === 0) {
                        console.log('No permissions found, resetting all checkboxes');
                        document.querySelectorAll('input[type="checkbox"][id^="id_app_"]').forEach(checkbox => {
                            checkbox.checked = false;
                        });
                        return;
                    }
                    
                    // Check if permissions data is not as expected
                    if (typeof data === 'object' && 'error' in data) {
                        console.error('Error in permissions data:', data.error);
                        return;
                    }
                    
                    // Update checkboxes with permissions
                    Object.keys(data).forEach(appName => {
                        const fieldName = `app_${appName}`;
                        console.log(`Looking for checkbox for app: ${appName}, field name: ${fieldName}`);
                        
                        const checkbox = document.getElementById(`id_${fieldName}`);
                        if (checkbox) {
                            checkbox.checked = data[appName];
                            console.log(`Set ${fieldName} to ${data[appName]}`);
                        } else {
                            console.warn(`Checkbox not found for app: ${appName}`);
                            
                            // Try alternative selectors
                            const altCheckbox = document.querySelector(`input[name="${fieldName}"]`);
                            if (altCheckbox) {
                                altCheckbox.checked = data[appName];
                                console.log(`Found and set checkbox by name: ${fieldName} to ${data[appName]}`);
                            } else {
                                // Try direct app name matching
                                const directCheckbox = document.getElementById(`id_app_${appName}`);
                                if (directCheckbox) {
                                    directCheckbox.checked = data[appName];
                                    console.log(`Found and set checkbox directly: id_app_${appName} to ${data[appName]}`);
                                } else {
                                    // Log all checkboxes to help debugging
                                    console.log(`All checkboxes for debug:`, document.querySelectorAll('input[type="checkbox"]'));
                                }
                            }
                        }
                    });
                })
                .catch(error => {
                    console.error('Error fetching permissions:', error);
                });
        }
        
        // Add change event listener
        userSelect.addEventListener('change', function() {
            const userId = this.value;
            console.log('User selection changed to:', userId);
            
            if (userId) {
                loadPermissionsForUser(userId);
            } else {
                console.log('No user selected, clearing checkboxes');
                // Clear all checkboxes
                document.querySelectorAll('input[type="checkbox"][id^="id_app_"]').forEach(checkbox => {
                    checkbox.checked = false;
                });
            }
        });
        
        // Trigger change event if value is already set (for edit forms)
        if (userSelect.value) {
            console.log('User already selected, triggering change event');
            // Use setTimeout to ensure DOM is fully loaded
            setTimeout(() => {
                loadPermissionsForUser(userSelect.value);
            }, 300);
        }
    } else {
        console.warn('User select element not found. Current URL:', window.location.href);
        console.warn('Document body:', document.body.innerHTML);
    }
}); 