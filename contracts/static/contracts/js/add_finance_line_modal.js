/**
 * Add Finance Line Modal — Finance Audit page (inline triggers) + future reuse
 * Depends on: window.financeClinList, window.financeShipmentsByClin,
 * refreshFinanceLinesForClin, refreshPartialFinanceLines, refreshContractSummary
 */
(function() {
    'use strict';

    const MODAL_ID = 'addFinanceLineModal';

    function getCsrfToken() {
        const el = document.querySelector('[name=csrfmiddlewaretoken]');
        return el ? el.value : '';
    }

    function markInvalid(id) {
        const el = document.getElementById(id);
        if (el) el.classList.add('is-invalid');
    }

    function showAflError(msg) {
        const err = document.getElementById('aflError');
        if (!err) return;
        err.textContent = msg;
        err.classList.remove('d-none');
    }

    function hideAflError() {
        const err = document.getElementById('aflError');
        if (!err) return;
        err.textContent = '';
        err.classList.add('d-none');
    }

    function resetAflModal() {
        document.getElementById('aflClinSelect').value = '';
        document.getElementById('aflShipmentSelect').innerHTML =
            '<option value="">— CLIN-level (no shipment) —</option>';
        document.getElementById('aflLineType').value = '';
        document.getElementById('aflDescription').value = '';
        document.getElementById('aflAmountBilled').value = '';
        document.getElementById('aflAmountPaid').value = '';
        document.getElementById('aflDate').value = '';
        document.getElementById('aflRefNum').value = '';
        hideAflError();

        const paid = document.getElementById('aflAmountPaid');
        if (paid) paid.dataset.manuallyEdited = '';

        ['aflClinSelect', 'aflLineType', 'aflAmountBilled', 'aflAmountPaid', 'aflDate']
            .forEach(function(id) {
                const el = document.getElementById(id);
                if (el) el.classList.remove('is-invalid');
            });

        const saveBtn = document.getElementById('aflSaveBtn');
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.textContent = 'Save';
        }

        document.getElementById('aflClinSelectRow').style.display = '';
        document.getElementById('aflShipmentRow').style.display = '';
    }

    function toastSuccess(msg) {
        if (typeof window.notify === 'function') {
            window.notify('success', msg, 3000);
        }
    }

    function extractFinanceLineId(data) {
        if (!data) return null;
        if (data.finance_line_id) return data.finance_line_id;
        if (data.finance_line && data.finance_line.id) return data.finance_line.id;
        return null;
    }

    function afterSaveSuccess(clinId, shipmentId) {
        if (typeof refreshFinanceLinesForClin === 'function') {
            refreshFinanceLinesForClin(clinId);
        }
        if (shipmentId && typeof refreshPartialFinanceLines === 'function') {
            refreshPartialFinanceLines(shipmentId, clinId);
        }

        if (shipmentId) {
            const acc = document.getElementById('partial-fl-accordion-' + shipmentId);
            if (acc) acc.style.display = 'table-row';
            const partialsAcc = document.getElementById('partials-accordion-' + clinId);
            if (partialsAcc) partialsAcc.style.display = '';
        } else {
            const acc = document.getElementById('accordion-' + clinId);
            if (acc) acc.style.display = 'table-row';
        }

        setTimeout(function() {
            if (typeof refreshClinRow === 'function') {
                refreshClinRow(clinId);
            }
            if (typeof refreshContractSummary === 'function') {
                refreshContractSummary();
            }
        }, 200);

        toastSuccess('Finance line added successfully');

        const modalEl = document.getElementById(MODAL_ID);
        const instance = bootstrap.Modal.getInstance(modalEl);
        if (instance) instance.hide();
    }

    function populateShipmentOptions(clinId, selectedShipmentId) {
        const shipSelect = document.getElementById('aflShipmentSelect');
        shipSelect.innerHTML =
            '<option value="">— CLIN-level (no shipment) —</option>';
        if (!clinId) return;
        const shipments = (window.financeShipmentsByClin || {})[clinId] ||
            (window.financeShipmentsByClin || {})[String(clinId)] || [];
        shipments.forEach(function(s) {
            const opt = document.createElement('option');
            opt.value = s.id;
            const name = s.name || ('Shipment ' + s.counter);
            const date = s.ship_date ? (' · ' + s.ship_date) : '';
            opt.textContent = name + date;
            if (selectedShipmentId && String(s.id) === String(selectedShipmentId)) {
                opt.selected = true;
            }
            shipSelect.appendChild(opt);
        });
    }

    function openAddFinanceLineModal(clinId, shipmentId) {
        const modalEl = document.getElementById(MODAL_ID);
        if (!modalEl) return;

        resetAflModal();
        document.getElementById('aflDate').value =
            new Date().toISOString().split('T')[0];

        const clinSelect = document.getElementById('aflClinSelect');
        clinSelect.innerHTML = '<option value="">— Select a CLIN —</option>';
        (window.financeClinList || []).forEach(function(clin) {
            const opt = document.createElement('option');
            opt.value = clin.id;
            opt.textContent = clin.item_number + ' — ' + clin.supplier_name;
            if (clinId && String(clin.id) === String(clinId)) {
                opt.selected = true;
            }
            clinSelect.appendChild(opt);
        });

        if (clinId) {
            document.getElementById('aflClinSelectRow').style.display = 'none';
            populateShipmentOptions(clinId, shipmentId || '');
            if (shipmentId) {
                document.getElementById('aflShipmentRow').style.display = 'none';
            }
        }

        new bootstrap.Modal(modalEl).show();
    }

    window.openAddFinanceLineModal = openAddFinanceLineModal;

    function init() {
        const modalEl = document.getElementById(MODAL_ID);
        if (!modalEl) return;

        document.addEventListener('click', function(e) {
            const btn = e.target.closest('.js-open-add-finance-line');
            if (!btn) return;
            openAddFinanceLineModal(btn.dataset.clinId, btn.dataset.shipmentId || '');
        });

        document.getElementById('aflClinSelect').addEventListener('change', function() {
            populateShipmentOptions(this.value, '');
        });

        document.getElementById('aflAmountBilled').addEventListener('input', function() {
            const paid = document.getElementById('aflAmountPaid');
            if (!paid.dataset.manuallyEdited) {
                paid.value = this.value;
            }
        });

        document.getElementById('aflAmountPaid').addEventListener('input', function() {
            this.dataset.manuallyEdited = 'true';
        });

        document.getElementById('aflSaveBtn').addEventListener('click', function() {
            hideAflError();
            ['aflClinSelect', 'aflLineType', 'aflAmountBilled', 'aflAmountPaid', 'aflDate']
                .forEach(function(id) {
                    const el = document.getElementById(id);
                    if (el) el.classList.remove('is-invalid');
                });

            const clinId = document.getElementById('aflClinSelect').value;
            const shipmentId = document.getElementById('aflShipmentSelect').value;
            const lineType = document.getElementById('aflLineType').value.trim();
            const description = document.getElementById('aflDescription').value.trim();
            const amountBilled = parseFloat(document.getElementById('aflAmountBilled').value);
            const amountPaid = parseFloat(document.getElementById('aflAmountPaid').value);
            const date = document.getElementById('aflDate').value;
            const refNum = document.getElementById('aflRefNum').value.trim();

            let valid = true;
            if (!clinId) { markInvalid('aflClinSelect'); valid = false; }
            if (!lineType) { markInvalid('aflLineType'); valid = false; }
            if (isNaN(amountBilled) || amountBilled <= 0) {
                markInvalid('aflAmountBilled');
                valid = false;
            }
            if (isNaN(amountPaid) || amountPaid < 0) {
                markInvalid('aflAmountPaid');
                valid = false;
            }
            if (!date) { markInvalid('aflDate'); valid = false; }
            if (!valid) return;

            const saveBtn = document.getElementById('aflSaveBtn');
            saveBtn.disabled = true;
            saveBtn.textContent = 'Saving…';

            const csrfToken = getCsrfToken();
            const addUrl = shipmentId
                ? '/contracts/api/finance-lines/partial/' + shipmentId + '/add/'
                : '/contracts/api/finance-lines/add/';
            const addPayload = shipmentId
                ? {
                    line_type: lineType,
                    description: description,
                    amount_billed: amountBilled,
                }
                : {
                    clin_id: parseInt(clinId, 10),
                    line_type: lineType,
                    description: description,
                    amount_billed: amountBilled,
                };

            fetch(addUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                },
                body: JSON.stringify(addPayload),
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success) {
                    saveBtn.disabled = false;
                    saveBtn.textContent = 'Save';
                    showAflError(data.error || 'Failed to add finance line.');
                    return;
                }

                const financeLineId = extractFinanceLineId(data);
                if (!financeLineId) {
                    saveBtn.disabled = false;
                    saveBtn.textContent = 'Save';
                    showAflError('Finance line created but no ID returned.');
                    return;
                }

                if (amountPaid === 0) {
                    saveBtn.disabled = false;
                    saveBtn.textContent = 'Save';
                    afterSaveSuccess(clinId, shipmentId || null);
                    return;
                }

                return fetch(
                    '/contracts/api/finance-lines/' + financeLineId + '/log-payment/',
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': csrfToken,
                        },
                        body: JSON.stringify({
                            payment_amount: amountPaid,
                            payment_date: date,
                            payment_info: refNum,
                        }),
                    }
                )
                .then(function(r) { return r.json(); })
                .then(function(payData) {
                    saveBtn.disabled = false;
                    saveBtn.textContent = 'Save';
                    if (!payData.success) {
                        showAflError(
                            payData.error ||
                            'Finance line created but payment could not be logged.'
                        );
                        return;
                    }
                    afterSaveSuccess(clinId, shipmentId || null);
                });
            })
            .catch(function() {
                saveBtn.disabled = false;
                saveBtn.textContent = 'Save';
                showAflError('Network error. Please try again.');
            });
        });

        modalEl.addEventListener('hidden.bs.modal', resetAflModal);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
