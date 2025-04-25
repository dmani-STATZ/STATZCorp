// CLIN Shipments Module
const ClinShipments = {
    init() {
        console.log('Initializing ClinShipments module'); // Debug log
        
        // Initialize toggle functionality for all modes
        document.querySelectorAll('.section-header').forEach(header => {
            console.log('Found section header:', header); // Debug log
            
            header.addEventListener('click', (e) => {
                // Don't toggle if clicking the Add New Shipment button
                if (e.target.closest('button')) return;
                
                e.preventDefault();
                const section = header.closest('.section');
                console.log('Found section:', section); // Debug log
                
                if (!section) return;
                
                const tableContainer = section.querySelector('.overflow-x-auto');
                console.log('Found table container:', tableContainer); // Debug log
                
                if (tableContainer) {
                    tableContainer.classList.toggle('hidden');
                    // Update text
                    const toggleText = header.querySelector('.text-gray-500');
                    if (toggleText) {
                        toggleText.textContent = tableContainer.classList.contains('hidden') ? 
                            '(Click to expand)' : '(Click to collapse)';
                    }
                }
            });
        });

        // Only initialize form-specific functionality if we're in form mode
        const section = document.querySelector('.section');
        if (section && section.dataset.mode === 'form') {
            this.updateTotalShipQty();
        }
    },

    showMessage(message, type) {
        // You can customize this to show messages however you want
        console.log(`${type}: ${message}`);
        
        // Example toast notification (you can implement your own)
        if (typeof Toastify !== 'undefined') {
            Toastify({
                text: message,
                duration: 3000,
                gravity: "top",
                position: "right",
                backgroundColor: type === 'error' ? "#EF4444" : "#10B981"
            }).showToast();
        }
    },

    updateTotalShipQty() {
        const shipQtys = document.querySelectorAll('input[name$="-qty"]');
        let totalQty = 0;

        shipQtys.forEach(input => {
            totalQty += parseFloat(input.value || 0);
        });

        const totalQtySpan = document.getElementById('totalShipQty');
        if (totalQtySpan) totalQtySpan.textContent = totalQty.toFixed(2);
    },

    addNewShipment() {
        const table = document.querySelector('#shipments-table');
        
        // Remove the "No shipments found" message if it exists
        const noShipmentsMsg = document.getElementById('no-shipments-message');
        if (noShipmentsMsg) {
            noShipmentsMsg.closest('tr').remove();
        }
        
        const timestamp = new Date().getTime(); // Use timestamp as temporary ID
        
        // Get today's date in YYYY-MM-DD format
        const today = new Date().toISOString().split('T')[0];
        
        // Get the CLIN's UOM from the shipping_uom_display field
        const clinUom = document.getElementById('shipping_uom_display').value || 'EA';
        
        const newRow = document.createElement('tr');
        newRow.className = 'shipment-row unsaved-shipment';
        newRow.innerHTML = `
            <td class="px-4 py-3 relative">
                <div class="flex items-center gap-2">
                    <label for="ship-date-new-${timestamp}" class="sr-only">Ship Date</label>
                    <input type="date" 
                           id="ship-date-new-${timestamp}"
                           name="shipments-new-${timestamp}-date" 
                           value="${today}"
                           class="flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-yellow-50">
                    <span class="bg-yellow-200 text-yellow-800 text-xs font-medium px-2 py-1 rounded whitespace-nowrap">
                        Unsaved
                    </span>
                    <input type="hidden" 
                           id="shipment-id-new-${timestamp}"
                           name="shipments-new-${timestamp}-id" 
                           value="">
                </div>
            </td>
            <td class="px-4 py-3">
                <label for="ship-qty-new-${timestamp}" class="sr-only">Ship Quantity</label>
                <input type="number" 
                       id="ship-qty-new-${timestamp}"
                       step="0.01" 
                       name="shipments-new-${timestamp}-qty" 
                       class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-yellow-50">
            </td>
            <td class="px-4 py-3">
                <label for="ship-uom-new-${timestamp}" class="sr-only">Unit of Measure</label>
                <input type="text" 
                       id="ship-uom-new-${timestamp}"
                       name="shipments-new-${timestamp}-uom" 
                       value="${clinUom}"
                       class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-yellow-50">
            </td>
            <td class="px-4 py-3">
                <label for="ship-comments-new-${timestamp}" class="sr-only">Comments</label>
                <input type="text" 
                       id="ship-comments-new-${timestamp}"
                       name="shipments-new-${timestamp}-comments" 
                       class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-yellow-50">
            </td>
            <td class="px-4 py-3">
                <div class="flex justify-center space-x-2">
                    <button type="button" 
                            onclick="ClinShipments.saveShipment(this)" 
                            class="text-green-600 hover:text-green-900"
                            title="Save Shipment">
                        <svg fill="#000000" width="20px" height="20px" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" data-name="Layer 1">
                            <path d="M20.71,9.29l-6-6a1,1,0,0,0-.32-.21A1.09,1.09,0,0,0,14,3H6A3,3,0,0,0,3,6V18a3,3,0,0,0,3,3H18a3,3,0,0,0,3-3V10A1,1,0,0,0,20.71,9.29ZM9,5h4V7H9Zm6,14H9V16a1,1,0,0,1,1-1h4a1,1,0,0,1,1,1Zm4-1a1,1,0,0,1-1,1H17V16a3,3,0,0,0-3-3H10a3,3,0,0,0-3,3v3H6a1,1,0,0,1-1-1V6A1,1,0,0,1,6,5H7V8A1,1,0,0,0,8,9h6a1,1,0,0,0,1-1V6.41l4,4Z"/>
                        </svg>
                    </button>
                    <button type="button" 
                            onclick="ClinShipments.removeShipment(this)" 
                            class="text-red-600 hover:text-red-900"
                            title="Delete Shipment">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                        </svg>
                    </button>
                </div>
            </td>
        `;
        
        table.appendChild(newRow);
        this.updateTotalShipQty();
    },

    async saveShipment(button) {
        const row = button.closest('tr');
        const section = document.querySelector('.section');
        const clinId = section.dataset.clinId;

        if (!clinId) {
            this.showMessage('Please save the CLIN first before adding shipments.', 'error');
            return;
        }

        const shipmentId = row.querySelector('input[name$="-id"]').value;
        const dateInput = row.querySelector('input[name$="-date"]');
        const qtyInput = row.querySelector('input[name$="-qty"]');
        const uomInput = row.querySelector('input[name$="-uom"]');
        const commentsInput = row.querySelector('input[name$="-comments"]');

        // Validate required fields
        if (!dateInput.value) {
            this.showMessage('Ship date is required', 'error');
            dateInput.focus();
            return;
        }

        if (!qtyInput.value || parseFloat(qtyInput.value) <= 0) {
            this.showMessage('Valid quantity is required', 'error');
            qtyInput.focus();
            return;
        }

        const shipmentData = {
            clin_id: clinId,
            ship_date: dateInput.value,
            ship_qty: parseFloat(qtyInput.value) || 0.00,
            uom: uomInput.value.trim() || document.getElementById('shipping_uom_display').value || 'EA',
            comments: commentsInput.value.trim()
        };

        try {
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
            const url = shipmentId ? `/contracts/api/shipments/update/${shipmentId}/` : '/contracts/api/shipments/create/';
            
            console.log('Sending request to:', url);
            console.log('With data:', shipmentData);

            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify(shipmentData)
            });

            if (!response.ok) {
                const contentType = response.headers.get('content-type');
                if (contentType && contentType.includes('application/json')) {
                    const errorData = await response.json();
                    throw new Error(errorData.error || 'Failed to save shipment');
                } else {
                    const text = await response.text();
                    console.error('Server response:', text);
                    throw new Error(`Server error: ${response.status}`);
                }
            }

            const data = await response.json();

            if (data.success) {
                // Remove the "No shipments found" message if it exists
                const noShipmentsMsg = document.getElementById('no-shipments-message');
                if (noShipmentsMsg) {
                    noShipmentsMsg.closest('tr').remove();
                }

                if (!shipmentId) {
                    row.querySelector('input[name$="-id"]').value = data.shipment_id;
                    row.classList.remove('unsaved-shipment');
                    
                    // Update input names with new shipment ID
                    dateInput.name = `shipments-${data.shipment_id}-date`;
                    qtyInput.name = `shipments-${data.shipment_id}-qty`;
                    uomInput.name = `shipments-${data.shipment_id}-uom`;
                    commentsInput.name = `shipments-${data.shipment_id}-comments`;
                    
                    // Ensure the date is properly displayed
                    if (data.ship_date) {
                        dateInput.value = data.ship_date;
                    } else {
                        const savedDate = new Date(dateInput.value);
                        const formattedDate = savedDate.toISOString().split('T')[0];
                        dateInput.value = formattedDate;
                    }
                    
                    // Remove yellow background from all inputs
                    [dateInput, qtyInput, uomInput, commentsInput].forEach(input => {
                        input.classList.remove('bg-yellow-50');
                    });
                    
                    // Remove the "Unsaved" label, but keep the parent div
                    const unsavedLabel = row.querySelector('.bg-yellow-200');
                    if (unsavedLabel) unsavedLabel.remove();
                }
                
                this.showMessage('Shipment saved successfully', 'success');
                this.updateTotalShipQty();
            } else {
                throw new Error(data.error || 'Failed to save shipment');
            }
        } catch (error) {
            console.error('Save shipment error:', error);
            this.showMessage('Error saving shipment: ' + error.message, 'error');
        }
    },

    async removeShipment(button) {
        const row = button.closest('tr');
        const section = document.querySelector('.section');
        const clinId = section.dataset.clinId;
        const shipmentId = row.querySelector('input[name$="-id"]').value;

        if (!shipmentId) {
            row.remove();
            this.updateTotalShipQty();
            return;
        }

        try {
            const response = await fetch(`/contracts/api/shipments/delete/${shipmentId}/`, {
                method: 'POST',
                headers: {
                    'Accept': 'application/json',
                    'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
                }
            });

            const data = await response.json();

            if (data.success) {
                row.remove();
                this.updateTotalShipQty();
                this.showMessage('Shipment deleted successfully', 'success');
            } else {
                throw new Error(data.error || 'Failed to delete shipment');
            }
        } catch (error) {
            console.error('Delete shipment error:', error);
            this.showMessage('Error deleting shipment: ' + error.message, 'error');
        }
    }
};

// Initialize when the DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM Content Loaded - Initializing ClinShipments'); // Debug log
    ClinShipments.init();
}); 