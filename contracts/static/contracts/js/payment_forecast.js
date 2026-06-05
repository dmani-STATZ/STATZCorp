(function() {
    'use strict';

    // Helper function to save payment plan properties via API
    function savePaymentPlan(shipmentId, payload, element) {
        const url = window.upsertPaymentPlanUrlTemplate.replace('0', shipmentId);
        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

        fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify(payload)
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                if (typeof window.notify === 'function') {
                    window.notify('success', 'Payment plan updated.');
                }
            } else {
                if (typeof window.notify === 'function') {
                    window.notify('error', 'Error updating plan: ' + data.error);
                }
            }
        })
        .catch(err => {
            console.error(err);
            if (typeof window.notify === 'function') {
                window.notify('error', 'Network error while updating payment plan.');
            }
        });
    }

    // Delegated click handler for opening payment history popup
    document.addEventListener('click', function(e) {
        const cell = e.target.closest('.partial-value-cell');
        if (!cell) return;

        const entityType = cell.dataset.entityType;
        const entityId = cell.dataset.entityId;
        const paymentType = cell.dataset.paymentType;
        const currentValue = cell.dataset.currentValue;

        if (entityType && entityId && paymentType && typeof window.openPaymentHistoryPopup === 'function') {
            window.openPaymentHistoryPopup(
                entityType,
                entityId,
                paymentType,
                'finance_audit', // reuse finance_audit popup logic
                currentValue
            );
        }
    });

    // Delegated change handler for inline terms and plan edits (dates, checkboxes)
    document.addEventListener('change', function(e) {
        // 1. Inline Special Payment Term selection
        const termSelect = e.target.closest('.js-forecast-term-select');
        if (termSelect) {
            const clinId = termSelect.dataset.clinId;
            const value = termSelect.value;
            const url = window.updateClinFieldUrlTemplate.replace('0', clinId);
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

            fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({
                    field: 'special_payment_terms',
                    value: value || null
                })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    if (typeof window.notify === 'function') {
                        window.notify('success', 'Payment term updated.');
                    }
                    // Term changes affect due dates, trigger reload so they recompute
                    setTimeout(() => {
                        window.location.reload();
                    }, 500);
                } else {
                    if (typeof window.notify === 'function') {
                        window.notify('error', 'Error: ' + data.error);
                    }
                }
            })
            .catch(err => {
                console.error(err);
                if (typeof window.notify === 'function') {
                    window.notify('error', 'Network error while updating terms.');
                }
            });
            return;
        }

        // 2. Planned Pay Date edit
        const dateInput = e.target.closest('.js-plan-date');
        if (dateInput) {
            const shipmentId = dateInput.dataset.shipmentId;
            savePaymentPlan(shipmentId, {
                planned_pay_date: dateInput.value
            }, dateInput);
            return;
        }

        // 3. On Hold toggle
        const holdInput = e.target.closest('.js-plan-hold');
        if (holdInput) {
            const shipmentId = holdInput.dataset.shipmentId;
            savePaymentPlan(shipmentId, {
                on_hold: holdInput.checked
            }, holdInput);
            return;
        }
    });

    // Delegated focusout (blur) handler for notes
    document.addEventListener('focusout', function(e) {
        const noteInput = e.target.closest('.js-plan-note');
        if (noteInput) {
            const shipmentId = noteInput.dataset.shipmentId;
            savePaymentPlan(shipmentId, {
                note: noteInput.value
            }, noteInput);
        }
    });

    // Expose updateCellValue globally so the ledger popup calls it on update
    window.updateCellValue = function(entityId, fieldType, newValue) {
        const cell = document.querySelector(
            `.partial-value-cell[data-entity-id="${entityId}"][data-payment-type="${fieldType}"]`
        );
        if (cell) {
            const numericTotal = parseFloat(newValue) || 0;
            cell.textContent = `$${numericTotal.toFixed(2)}`;
            cell.dataset.currentValue = numericTotal.toFixed(2);

            const row = cell.closest('tr');
            if (row) {
                const amountCell = row.querySelector('.js-amount-cell');
                const outstandingCell = row.querySelector('.js-outstanding-cell');
                if (amountCell && outstandingCell) {
                    const amount = parseFloat(amountCell.dataset.amount) || 0;
                    const outstanding = amount - numericTotal;
                    outstandingCell.textContent = `$${outstanding.toFixed(2)}`;
                    outstandingCell.dataset.outstanding = outstanding.toFixed(2);
                    
                    if (outstanding <= 0) {
                        row.classList.add('table-success', 'text-decoration-line-through');
                        row.style.opacity = '0.6';
                    } else {
                        row.classList.remove('table-success', 'text-decoration-line-through');
                        row.style.opacity = '1';
                    }
                }
            }
        }
    };

})();
