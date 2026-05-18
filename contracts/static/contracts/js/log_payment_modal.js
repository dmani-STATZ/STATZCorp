/**
 * Log Payment Modal — Finance Audit page
 * Depends on: window.financeClinList, window.financeShipmentsByClin,
 * Bootstrap 5, /contracts/api/partials/add/, /contracts/api/partials/auto-calc/,
 * /contracts/api/payment-history/clinshipment/{id}/{paymentType}/
 */
(function() {
    'use strict';

    let lpQuoteValue = null;
    let lpItemValue = null;

    function formatMoney(val) {
        if (val === null || val === undefined || isNaN(val)) return '—';
        return '$' + Number(val).toLocaleString('en-US', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    function getCsrfToken() {
        const el = document.querySelector('#logPaymentModal [name=csrfmiddlewaretoken]')
            || document.querySelector('[name=csrfmiddlewaretoken]');
        return el ? el.value : '';
    }

    function showLpError(msg) {
        const err = document.getElementById('lpError');
        if (!err) return;
        err.textContent = msg;
        err.classList.remove('d-none');
    }

    function hideLpError() {
        const err = document.getElementById('lpError');
        if (!err) return;
        err.textContent = '';
        err.classList.add('d-none');
    }

    function clearInvalid(...ids) {
        ids.forEach(function(id) {
            const el = document.getElementById(id);
            if (el) el.classList.remove('is-invalid');
        });
    }

    function resetLogPaymentModal() {
        hideLpError();
        lpQuoteValue = null;
        lpItemValue = null;

        const clinSelect = document.getElementById('lpClinSelect');
        if (clinSelect) clinSelect.value = '';

        document.getElementById('lpShipmentSection').style.display = 'none';
        document.getElementById('lpNewShipmentSection').style.display = 'none';

        const shipmentSelect = document.getElementById('lpShipmentSelect');
        if (shipmentSelect) {
            shipmentSelect.innerHTML = '<option value="">— Select a shipment —</option>';
            shipmentSelect.value = '';
        }

        document.getElementById('lpNewShipmentName').textContent = '';
        document.getElementById('lpNewQty').value = '';
        document.getElementById('lpNewShipDate').value = '';
        document.getElementById('lpNewQuoteValue').textContent = '—';
        document.getElementById('lpNewItemValue').textContent = '—';

        document.getElementById('lpTypeCustomerPay').checked = true;
        document.getElementById('lpAmount').value = '';
        document.getElementById('lpDate').value = '';
        document.getElementById('lpRefNum').value = '';
        document.getElementById('lpInfo').value = '';

        clearInvalid(
            'lpClinSelect', 'lpShipmentSelect', 'lpNewQty',
            'lpAmount', 'lpDate'
        );

        const saveBtn = document.getElementById('lpSaveBtn');
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.textContent = 'Save';
        }
    }

    function populateClinDropdown() {
        const select = document.getElementById('lpClinSelect');
        if (!select) return;

        select.innerHTML = '<option value="">— Select a CLIN —</option>';
        const list = window.financeClinList || [];
        list.forEach(function(clin) {
            const opt = document.createElement('option');
            opt.value = clin.id;
            opt.textContent = clin.item_number + ' — ' + clin.supplier_name +
                ' (' + clin.shipped_qty + '/' + clin.order_qty + ' shipped)';
            select.appendChild(opt);
        });
    }

    function findClin(clinId) {
        return (window.financeClinList || []).find(function(c) {
            return String(c.id) === String(clinId);
        });
    }

    function runAutoCalc(clinId, qty) {
        if (!clinId || !qty || parseFloat(qty) <= 0) {
            lpQuoteValue = null;
            lpItemValue = null;
            document.getElementById('lpNewQuoteValue').textContent = '—';
            document.getElementById('lpNewItemValue').textContent = '—';
            return;
        }

        fetch('/contracts/api/partials/auto-calc/?clin_id=' +
            encodeURIComponent(clinId) + '&ship_qty=' + encodeURIComponent(qty))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.success) {
                    lpQuoteValue = data.auto_quote_value;
                    lpItemValue = data.auto_item_value;
                    document.getElementById('lpNewQuoteValue').textContent =
                        formatMoney(lpQuoteValue);
                    document.getElementById('lpNewItemValue').textContent =
                        formatMoney(lpItemValue);
                }
            })
            .catch(function(err) { console.debug('Auto-calc error:', err); });
    }

    function onClinSelectChange() {
        const clinId = document.getElementById('lpClinSelect').value;
        hideLpError();
        clearInvalid('lpClinSelect', 'lpShipmentSelect', 'lpNewQty');

        document.getElementById('lpShipmentSection').style.display = 'none';
        document.getElementById('lpNewShipmentSection').style.display = 'none';

        if (!clinId) return;

        const shipments = (window.financeShipmentsByClin || {})[String(clinId)] || [];

        if (shipments.length > 0) {
            const shipmentSelect = document.getElementById('lpShipmentSelect');
            shipmentSelect.innerHTML = '<option value="">— Select a shipment —</option>';
            shipments.forEach(function(shipment) {
                const opt = document.createElement('option');
                opt.value = shipment.id;
                const displayName = shipment.name || ('Shipment ' + shipment.counter);
                const dateStr = shipment.ship_date ? (' · ' + shipment.ship_date) : '';
                opt.textContent = displayName + dateStr;
                shipmentSelect.appendChild(opt);
            });
            document.getElementById('lpShipmentSection').style.display = '';
        } else {
            const clin = findClin(clinId);
            document.getElementById('lpNewShipmentName').textContent = 'Shipment 1';
            const qtyInput = document.getElementById('lpNewQty');
            if (clin && clin.order_qty) {
                qtyInput.value = clin.order_qty;
                runAutoCalc(clinId, clin.order_qty);
            } else {
                qtyInput.value = '';
                document.getElementById('lpNewQuoteValue').textContent = '—';
                document.getElementById('lpNewItemValue').textContent = '—';
            }
            document.getElementById('lpNewShipDate').value = '';
            document.getElementById('lpNewShipmentSection').style.display = '';
        }
    }

    function postPayment(shipmentId, paymentType, payload) {
        return fetch(
            '/contracts/api/payment-history/clinshipment/' +
            shipmentId + '/' + paymentType + '/',
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken(),
                },
                body: JSON.stringify(payload),
            }
        ).then(function(r) { return r.json(); });
    }

    function notifySuccess(msg) {
        if (typeof window.notify === 'function') {
            window.notify('success', msg, 3000);
        }
    }

    document.addEventListener('DOMContentLoaded', function() {
        const openBtn = document.getElementById('btnLogPayment');
        const modalEl = document.getElementById('logPaymentModal');
        if (!openBtn || !modalEl) return;

        openBtn.addEventListener('click', function() {
            resetLogPaymentModal();
            populateClinDropdown();
            document.getElementById('lpDate').value =
                new Date().toISOString().split('T')[0];
            const modal = new bootstrap.Modal(modalEl);
            modal.show();
        });

        document.getElementById('lpClinSelect').addEventListener('change', onClinSelectChange);

        document.getElementById('lpNewQty').addEventListener('input', function() {
            const clinId = document.getElementById('lpClinSelect').value;
            runAutoCalc(clinId, this.value);
        });

        document.getElementById('lpSaveBtn').addEventListener('click', function() {
            hideLpError();
            clearInvalid(
                'lpClinSelect', 'lpShipmentSelect', 'lpNewQty',
                'lpAmount', 'lpDate'
            );

            const clinId = document.getElementById('lpClinSelect').value;
            const shipments = clinId
                ? ((window.financeShipmentsByClin || {})[String(clinId)] || [])
                : [];
            const isNewShipmentMode = clinId && shipments.length === 0;

            let valid = true;

            if (!clinId) {
                document.getElementById('lpClinSelect').classList.add('is-invalid');
                valid = false;
            }

            let shipmentId = null;
            if (isNewShipmentMode) {
                const qty = document.getElementById('lpNewQty').value;
                if (!qty || parseFloat(qty) <= 0) {
                    document.getElementById('lpNewQty').classList.add('is-invalid');
                    valid = false;
                }
            } else if (clinId) {
                shipmentId = document.getElementById('lpShipmentSelect').value;
                if (!shipmentId) {
                    document.getElementById('lpShipmentSelect').classList.add('is-invalid');
                    valid = false;
                }
            }

            const amount = document.getElementById('lpAmount').value;
            if (!amount || parseFloat(amount) <= 0) {
                document.getElementById('lpAmount').classList.add('is-invalid');
                valid = false;
            }

            const paymentDate = document.getElementById('lpDate').value;
            if (!paymentDate) {
                document.getElementById('lpDate').classList.add('is-invalid');
                valid = false;
            }

            if (!valid) {
                showLpError('Please correct the highlighted fields.');
                return;
            }

            const paymentType = document.querySelector(
                'input[name="lpPaymentType"]:checked'
            ).value;

            const paymentPayload = {
                payment_amount: parseFloat(amount),
                payment_date: paymentDate,
                reference_number: document.getElementById('lpRefNum').value || '',
                payment_info: document.getElementById('lpInfo').value || '',
            };

            const saveBtn = document.getElementById('lpSaveBtn');
            saveBtn.disabled = true;
            saveBtn.textContent = 'Saving...';

            let newShipmentCreated = false;

            function finishSuccess() {
                if (typeof refreshClinRow === 'function') refreshClinRow(clinId);
                if (typeof refreshContractSummary === 'function') refreshContractSummary();
                notifySuccess('Payment logged successfully');
                bootstrap.Modal.getInstance(modalEl).hide();
                if (newShipmentCreated) {
                    window.location.reload();
                }
            }

            function handlePaymentStep(resolvedShipmentId) {
                postPayment(resolvedShipmentId, paymentType, paymentPayload)
                    .then(function(data) {
                        if (data.success) {
                            finishSuccess();
                        } else {
                            showLpError(data.error || 'Failed to log payment');
                            saveBtn.disabled = false;
                            saveBtn.textContent = 'Save';
                        }
                    })
                    .catch(function() {
                        showLpError('Network error while logging payment');
                        saveBtn.disabled = false;
                        saveBtn.textContent = 'Save';
                    });
            }

            if (isNewShipmentMode) {
                const clin = findClin(clinId);
                const qtyVal = parseFloat(document.getElementById('lpNewQty').value);
                const partialPayload = {
                    clin_id: clinId,
                    name: null,
                    ship_qty: qtyVal,
                    ship_date: document.getElementById('lpNewShipDate').value || null,
                    uom: (clin && clin.uom) ? clin.uom : 'EA',
                    quote_value: lpQuoteValue != null ? lpQuoteValue : null,
                    item_value: lpItemValue != null ? lpItemValue : null,
                    paid_amount: null,
                    wawf_payment: null,
                    comments: '',
                };

                fetch('/contracts/api/partials/add/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken(),
                    },
                    body: JSON.stringify(partialPayload),
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.success && data.shipment && data.shipment.id) {
                        newShipmentCreated = true;
                        handlePaymentStep(data.shipment.id);
                    } else {
                        showLpError(data.error || 'Failed to create shipment');
                        saveBtn.disabled = false;
                        saveBtn.textContent = 'Save';
                    }
                })
                .catch(function() {
                    showLpError('Network error while creating shipment');
                    saveBtn.disabled = false;
                    saveBtn.textContent = 'Save';
                });
            } else {
                handlePaymentStep(shipmentId);
            }
        });

        modalEl.addEventListener('hidden.bs.modal', resetLogPaymentModal);
    });
})();
