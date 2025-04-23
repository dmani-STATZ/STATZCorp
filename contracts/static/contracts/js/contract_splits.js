// Contract Splits Module
const ContractSplits = {
    init() {
        // Initialize toggle functionality
        document.querySelectorAll('.toggle-splits').forEach(button => {
            button.addEventListener('click', (e) => {
                e.preventDefault(); // Prevent default button behavior
                const tableBody = button.closest('.section').querySelector('#splits-table');
                tableBody.classList.toggle('hidden');
                
                // Update button text
                const buttonText = tableBody.classList.contains('hidden') ? 'Show Splits' : 'Hide Splits';
                button.textContent = buttonText;
            });
        });

        // Initialize any existing splits
        this.updateTotalSplitValue();
    },

    showMessage(message, type) {
        // You can customize this to show messages however you want
        // For now, we'll just console.log
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

    updateTotalSplitValue() {
        const splitValues = document.querySelectorAll('input[name$="-value"]');
        const splitPaid = document.querySelectorAll('input[name$="-paid"]');
        let totalValue = 0;
        let totalPaid = 0;

        splitValues.forEach(input => {
            totalValue += parseFloat(input.value || 0);
        });

        splitPaid.forEach(input => {
            totalPaid += parseFloat(input.value || 0);
        });

        const totalValueSpan = document.getElementById('totalSplitValue');
        const totalPaidSpan = document.getElementById('totalSplitPaid');
        
        if (totalValueSpan) totalValueSpan.textContent = totalValue.toFixed(2);
        if (totalPaidSpan) totalPaidSpan.textContent = totalPaid.toFixed(2);

        // Update color based on plan_gross match
        const section = document.querySelector('.section');
        const planGross = parseFloat(section.dataset.planGross || 0);
        
        if (totalValueSpan) {
            const parent = totalValueSpan.closest('p');
            if (Math.abs(totalValue - planGross) < 0.01) {
                parent.classList.remove('text-red-500');
                parent.classList.add('text-green-500');
            } else {
                parent.classList.remove('text-green-500');
                parent.classList.add('text-red-500');
            }
        }
    },

    addNewSplit() {
        const table = document.querySelector('#splits-table');
        const timestamp = new Date().getTime(); // Use timestamp as temporary ID
        
        const newRow = document.createElement('tr');
        newRow.className = 'split-row unsaved-split';
        newRow.innerHTML = `
            <td class="px-4 py-3 relative">
                <div class="flex items-center gap-2">
                    <input type="text" 
                           name="splits-new-${timestamp}-company" 
                           class="flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-yellow-50">
                    <span class="bg-yellow-200 text-yellow-800 text-xs font-medium px-2 py-1 rounded whitespace-nowrap">
                        Unsaved
                    </span>
                </div>
                <input type="hidden" name="splits-new-${timestamp}-id" value="">
            </td>
            <td class="px-4 py-3">
                <input type="number" 
                       step="0.01" 
                       name="splits-new-${timestamp}-value" 
                       class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-yellow-50">
            </td>
            <td class="px-4 py-3">
                <input type="number" 
                       step="0.01" 
                       name="splits-new-${timestamp}-paid" 
                       class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-yellow-50">
            </td>
            <td class="px-4 py-3">
                <div class="flex justify-center space-x-2">
                    <button type="button" 
                            onclick="ContractSplits.saveSplit(this)" 
                            class="text-green-600 hover:text-green-900"
                            title="Save Split">
                        <svg fill="#000000" width="20px" height="20px" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" data-name="Layer 1">
                            <path d="M20.71,9.29l-6-6a1,1,0,0,0-.32-.21A1.09,1.09,0,0,0,14,3H6A3,3,0,0,0,3,6V18a3,3,0,0,0,3,3H18a3,3,0,0,0,3-3V10A1,1,0,0,0,20.71,9.29ZM9,5h4V7H9Zm6,14H9V16a1,1,0,0,1,1-1h4a1,1,0,0,1,1,1Zm4-1a1,1,0,0,1-1,1H17V16a3,3,0,0,0-3-3H10a3,3,0,0,0-3,3v3H6a1,1,0,0,1-1-1V6A1,1,0,0,1,6,5H7V8A1,1,0,0,0,8,9h6a1,1,0,0,0,1-1V6.41l4,4Z"/>
                        </svg>
                    </button>
                    <button type="button" 
                            onclick="ContractSplits.removeSplit(this)" 
                            class="text-red-600 hover:text-red-900"
                            title="Delete Split">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                        </svg>
                    </button>
                </div>
            </td>
        `;
        
        table.appendChild(newRow);
        this.updateTotalSplitValue();
    },

    async saveSplit(button) {
        const row = button.closest('tr');
        const section = document.querySelector('.section');
        const contractId = section.dataset.contractId;

        if (!contractId) {
            this.showMessage('Please save the contract first before adding splits.', 'error');
            return;
        }

        const splitId = row.querySelector('input[name$="-id"]').value;
        const companyInput = row.querySelector('input[name$="-company"]');
        const valueInput = row.querySelector('input[name$="-value"]');
        const paidInput = row.querySelector('input[name$="-paid"]');

        const splitData = {
            company_name: companyInput.value.trim(),
            split_value: parseFloat(valueInput.value) || 0.00,
            split_paid: parseFloat(paidInput.value) || 0.00
        };

        try {
            const url = splitId ? 
                `/contracts/api/splits/update/${splitId}/` :
                `/contracts/api/splits/create/`;
            
            if (!splitId) {
                splitData.contract_id = contractId;
            }

            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
                },
                body: JSON.stringify(splitData)
            });

            const data = await response.json();

            if (data.success) {
                if (!splitId) {
                    row.querySelector('input[name$="-id"]').value = data.split_id;
                    row.classList.remove('unsaved-split');
                    
                    companyInput.name = `splits-${data.split_id}-company`;
                    valueInput.name = `splits-${data.split_id}-value`;
                    paidInput.name = `splits-${data.split_id}-paid`;
                    
                    [companyInput, valueInput, paidInput].forEach(input => {
                        input.classList.remove('bg-yellow-50');
                    });
                    
                    const unsavedLabel = row.querySelector('.bg-yellow-200');
                    if (unsavedLabel) unsavedLabel.remove();
                }
                
                this.showMessage('Split saved successfully', 'success');
                this.updateTotalSplitValue();
            } else {
                throw new Error(data.error || 'Failed to save split');
            }
        } catch (error) {
            console.error('Save split error:', error);
            this.showMessage('Error saving split: ' + error.message, 'error');
        }
    },

    async removeSplit(button) {
        const row = button.closest('tr');
        const splitId = row.querySelector('input[name$="-id"]').value;

        if (!splitId) {
            row.remove();
            this.updateTotalSplitValue();
            return;
        }

        try {
            const response = await fetch(`/contracts/api/splits/delete/${splitId}/`, {
                method: 'POST',
                headers: {
                    'Accept': 'application/json',
                    'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
                }
            });

            const data = await response.json();

            if (data.success) {
                row.remove();
                this.updateTotalSplitValue();
                this.showMessage('Split deleted successfully', 'success');
            } else {
                throw new Error(data.error || 'Failed to delete split');
            }
        } catch (error) {
            console.error('Delete split error:', error);
            this.showMessage('Error deleting split: ' + error.message, 'error');
        }
    }
};

// Initialize when the DOM is ready
document.addEventListener('DOMContentLoaded', () => ContractSplits.init()); 