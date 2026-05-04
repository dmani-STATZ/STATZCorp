/**
 * Add Partial Shipment Modal
 * Shared between finance_audit.html and clin_detail.html (via clin_shipments.html)
 * Depends on: Bootstrap 5, /contracts/api/partials/add/, /contracts/api/partials/auto-calc/
 */
(function() {
    'use strict';

    function resetModal(clinId) {
        document.getElementById('addPartialClinId').value = clinId || '';
        document.getElementById('addPartialQty').value = '';
        document.getElementById('addPartialShipDate').value = '';
        document.getElementById('addPartialQuoteValue').value = '';
        document.getElementById('addPartialItemValue').value = '';
        document.getElementById('addPartialPaid').value = '';
        document.getElementById('addPartialCustomerPay').value = '';
        document.getElementById('addPartialComments').value = '';
        document.getElementById('addPartialAutoCalcNote').style.display = 'none';
        document.getElementById('addPartialUom').value = '';
    }

    // Open modal — delegated to handle dynamically rendered buttons
    document.addEventListener('click', function(e) {
        const btn = e.target.closest('.js-open-add-partial');
        if (!btn) return;
        const clinId = btn.dataset.clinId;
        resetModal(clinId);
        const modal = new bootstrap.Modal(
            document.getElementById('addPartialModal')
        );
        modal.show();
    });

    // Auto-calculate quote_value and item_value when QTY changes
    document.addEventListener('DOMContentLoaded', function() {
        const qtyInput = document.getElementById('addPartialQty');
        if (!qtyInput) return;

        qtyInput.addEventListener('input', function() {
            const clinId = document.getElementById('addPartialClinId').value;
            const qty = this.value;
            if (!clinId || !qty || parseFloat(qty) <= 0) return;

            fetch(`/contracts/api/partials/auto-calc/?clin_id=${encodeURIComponent(clinId)}&ship_qty=${encodeURIComponent(qty)}`)
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        const qv = document.getElementById('addPartialQuoteValue');
                        const iv = document.getElementById('addPartialItemValue');
                        const note = document.getElementById('addPartialAutoCalcNote');
                        // Only auto-fill if user hasn't manually entered a value
                        if (!qv.dataset.manuallyEdited) {
                            qv.value = data.auto_quote_value.toFixed(2);
                        }
                        if (!iv.dataset.manuallyEdited) {
                            iv.value = data.auto_item_value.toFixed(2);
                        }
                        if (note) note.style.display = 'block';
                    }
                })
                .catch(err => console.debug('Auto-calc error:', err));
        });

        // Track manual edits to quote/item value fields
        ['addPartialQuoteValue', 'addPartialItemValue'].forEach(function(id) {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener('input', function() {
                    this.dataset.manuallyEdited = '1';
                });
            }
        });

        // Clear manual edit flags when modal is hidden
        const modalEl = document.getElementById('addPartialModal');
        if (modalEl) {
            modalEl.addEventListener('hidden.bs.modal', function() {
                ['addPartialQuoteValue', 'addPartialItemValue'].forEach(function(id) {
                    const el = document.getElementById(id);
                    if (el) delete el.dataset.manuallyEdited;
                });
            });
        }

        // Save button
        const saveBtn = document.getElementById('addPartialSaveBtn');
        if (!saveBtn) return;

        saveBtn.addEventListener('click', function() {
            const clinId = document.getElementById('addPartialClinId').value;
            const qty = document.getElementById('addPartialQty').value;

            if (!qty || parseFloat(qty) <= 0) {
                if (window.notify) window.notify('error', 'QTY is required', 3000);
                else alert('QTY is required');
                return;
            }

            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
            const payload = {
                clin_id: clinId,
                ship_qty: parseFloat(qty),
                uom: document.getElementById('addPartialUom').value || '',
                ship_date: document.getElementById('addPartialShipDate').value || null,
                quote_value: document.getElementById('addPartialQuoteValue').value || null,
                item_value: document.getElementById('addPartialItemValue').value || null,
                paid_amount: document.getElementById('addPartialPaid').value || null,
                wawf_payment: document.getElementById('addPartialCustomerPay').value || null,
                comments: document.getElementById('addPartialComments').value || '',
            };

            // Disable save button to prevent double-submit
            saveBtn.disabled = true;
            saveBtn.textContent = 'Saving...';

            fetch('/contracts/api/partials/add/', {
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
                    bootstrap.Modal.getInstance(
                        document.getElementById('addPartialModal')
                    ).hide();
                    if (window.notify) window.notify('success', 'Partial shipment added', 3000);
                    window.location.reload();
                } else {
                    if (window.notify) window.notify('error', data.error || 'Failed to add partial', 3000);
                    else alert(data.error || 'Failed to add partial');
                    saveBtn.disabled = false;
                    saveBtn.textContent = 'Save';
                }
            })
            .catch(err => {
                console.error('Add partial error:', err);
                if (window.notify) window.notify('error', 'Network error', 3000);
                saveBtn.disabled = false;
                saveBtn.textContent = 'Save';
            });
        });
    });
})();
