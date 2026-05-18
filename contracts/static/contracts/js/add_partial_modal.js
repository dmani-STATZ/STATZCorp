/**
 * Add Partial Shipment Modal
 * Shared between finance_audit.html and clin_detail.html (via clin_shipments.html)
 * Depends on: Bootstrap 5, /contracts/api/partials/add/, /contracts/api/partials/auto-calc/
 */
(function() {
    'use strict';

    function resetModal() {
        document.getElementById('addPartialClinId').value = '';
        document.getElementById('addPartialName').value = '';
        document.getElementById('addPartialQty').value = '';
        document.getElementById('addPartialShipDate').value = '';
        document.getElementById('addPartialQuoteValue').value = '';
        document.getElementById('addPartialItemValue').value = '';
        document.getElementById('addPartialPaid').value = '';
        document.getElementById('addPartialCustomerPay').value = '';
        document.getElementById('addPartialComments').value = '';
        document.getElementById('addPartialAutoCalcNote').style.display = 'none';
        document.getElementById('addPartialUom').value = '';

        const clinSelect = document.getElementById('addPartialClinSelect');
        if (clinSelect) {
            clinSelect.value = '';
            clinSelect.classList.remove('is-invalid');
        }

        ['addPartialQuoteValue', 'addPartialItemValue'].forEach(function(id) {
            const el = document.getElementById(id);
            if (el) delete el.dataset.manuallyEdited;
        });
    }

    // Open modal — delegated to handle dynamically rendered buttons
    document.addEventListener('click', function(e) {
        const btn = e.target.closest('.js-open-add-partial');
        if (!btn) return;

        resetModal();

        const clinList = window.financeClinList;
        const clinSelect = document.getElementById('addPartialClinSelect');
        const clinSelectRow = document.getElementById('addPartialClinSelectRow');
        const btnClinId = btn.dataset.clinId;

        if (clinList && clinList.length > 0 && !btnClinId) {
            clinSelect.innerHTML = '<option value="">— Select a CLIN —</option>';
            clinList.forEach(function(clin) {
                const opt = document.createElement('option');
                opt.value = clin.id;
                opt.textContent = clin.item_number + ' — ' + clin.supplier_name +
                    ' (' + clin.shipped_qty + '/' + clin.order_qty + ' shipped)';
                clinSelect.appendChild(opt);
            });
            clinSelectRow.style.display = '';
            document.getElementById('addPartialClinId').value = '';
        } else if (btnClinId) {
            clinSelectRow.style.display = 'none';
            document.getElementById('addPartialClinId').value = btnClinId;
            const section = document.querySelector('.section[data-clin-id="' + btnClinId + '"]');
            const uomInput = document.getElementById('addPartialUom');
            if (section && section.dataset.uom && uomInput) {
                uomInput.value = section.dataset.uom;
            }
        } else {
            clinSelectRow.style.display = 'none';
        }

        const modal = new bootstrap.Modal(
            document.getElementById('addPartialModal')
        );
        modal.show();
    });

    document.addEventListener('DOMContentLoaded', function() {
        const clinSelect = document.getElementById('addPartialClinSelect');
        if (clinSelect) {
            clinSelect.addEventListener('change', function() {
                const clinId = this.value;
                document.getElementById('addPartialClinId').value = clinId;
                this.classList.remove('is-invalid');

                document.getElementById('addPartialQty').value = '';
                document.getElementById('addPartialQuoteValue').value = '';
                document.getElementById('addPartialItemValue').value = '';
                delete document.getElementById('addPartialQuoteValue').dataset.manuallyEdited;
                delete document.getElementById('addPartialItemValue').dataset.manuallyEdited;
                document.getElementById('addPartialAutoCalcNote').style.display = 'none';

                if (window.financeClinList && clinId) {
                    const clin = window.financeClinList.find(function(c) {
                        return String(c.id) === String(clinId);
                    });
                    if (clin) {
                        document.getElementById('addPartialUom').value = clin.uom || 'EA';
                    }
                }
            });
        }

        const qtyInput = document.getElementById('addPartialQty');
        if (!qtyInput) return;

        qtyInput.addEventListener('input', function() {
            const clinId = document.getElementById('addPartialClinId').value;
            const qty = this.value;
            if (!clinId || !qty || parseFloat(qty) <= 0) return;

            fetch('/contracts/api/partials/auto-calc/?clin_id=' + encodeURIComponent(clinId) + '&ship_qty=' + encodeURIComponent(qty))
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        const qv = document.getElementById('addPartialQuoteValue');
                        const iv = document.getElementById('addPartialItemValue');
                        const note = document.getElementById('addPartialAutoCalcNote');
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

        ['addPartialQuoteValue', 'addPartialItemValue'].forEach(function(id) {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener('input', function() {
                    this.dataset.manuallyEdited = '1';
                });
            }
        });

        const modalEl = document.getElementById('addPartialModal');
        if (modalEl) {
            modalEl.addEventListener('hidden.bs.modal', function() {
                ['addPartialQuoteValue', 'addPartialItemValue'].forEach(function(id) {
                    const el = document.getElementById(id);
                    if (el) delete el.dataset.manuallyEdited;
                });
                const select = document.getElementById('addPartialClinSelect');
                if (select) select.classList.remove('is-invalid');
            });
        }

        const saveBtn = document.getElementById('addPartialSaveBtn');
        if (!saveBtn) return;

        saveBtn.addEventListener('click', function() {
            const clinId = document.getElementById('addPartialClinId').value;
            const qty = document.getElementById('addPartialQty').value;

            if (!clinId) {
                document.getElementById('addPartialClinSelect').classList.add('is-invalid');
                return;
            }

            if (!qty || parseFloat(qty) <= 0) {
                if (window.notify) window.notify('error', 'QTY is required', 3000);
                else alert('QTY is required');
                return;
            }

            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
            const nameVal = document.getElementById('addPartialName').value.trim();
            const payload = {
                clin_id: clinId,
                name: nameVal || null,
                ship_qty: parseFloat(qty),
                uom: document.getElementById('addPartialUom').value || '',
                ship_date: document.getElementById('addPartialShipDate').value || null,
                quote_value: document.getElementById('addPartialQuoteValue').value || null,
                item_value: document.getElementById('addPartialItemValue').value || null,
                paid_amount: document.getElementById('addPartialPaid').value || null,
                wawf_payment: document.getElementById('addPartialCustomerPay').value || null,
                comments: document.getElementById('addPartialComments').value || '',
            };

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
