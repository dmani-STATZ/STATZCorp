/**
 * DFAS import review: per-row resolution, bulk apply, match preview, batch close.
 */
(function () {
    'use strict';

    const resolveState = {
        rowId: null,
        steps: ['contract', 'clin', 'shipment'],
        currentStepIndex: 0,
        contractId: null,
        clinId: null,
        clinHasShipments: false,
        shipmentId: null,
        rowRef: '',
    };

    const selectedRowIds = new Set();
    let matchedCount = 0;

    const RESOLVE_STEP_LABELS = {
        contract: 'Contract',
        clin: 'CLIN',
        shipment: 'Shipment',
    };

    let _preloadedShipments = null;

    function getCsrfToken() {
        const i = document.querySelector('[name=csrfmiddlewaretoken]');
        if (i && i.value) return i.value;
        const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }

    function rowResolveUrl(rowId) {
        const tpl = document.getElementById('dfasResolveRowUrlZero');
        if (!tpl || !tpl.value) return '';
        return tpl.value.replace(/\/rows\/0\//, '/rows/' + String(rowId) + '/');
    }

    function rowPreviewUrl(rowId) {
        const tpl = document.getElementById('dfasPreviewUrlZero');
        if (!tpl || !tpl.value) return '';
        return tpl.value.replace(/\/rows\/0\//, '/rows/' + String(rowId) + '/');
    }

    function applyRowsUrl() {
        const el = document.getElementById('dfasApplyRowsUrl');
        return el ? el.value : '';
    }

    function closeBatchUrl() {
        const el = document.getElementById('dfasCloseBatchUrl');
        return el ? el.value : '';
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, function (c) {
            return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
        });
    }

    function fmtMoney(val) {
        if (val == null || val === '') return '—';
        const n = parseFloat(val);
        if (Number.isNaN(n)) return '—';
        return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    // ── Checkbox / sticky bar state ───────────────────────────────────────────
    function getMatchedCheckboxes() {
        return Array.from(document.querySelectorAll('.dfas-row-checkbox'));
    }

    function syncSelectAllCheckbox() {
        const selectAll = document.getElementById('dfasSelectAllMatched');
        if (!selectAll) return;
        const boxes = getMatchedCheckboxes();
        if (!boxes.length) {
            selectAll.checked = false;
            selectAll.indeterminate = false;
            return;
        }
        const checkedCount = boxes.filter(cb => cb.checked).length;
        selectAll.checked = checkedCount === boxes.length;
        selectAll.indeterminate = checkedCount > 0 && checkedCount < boxes.length;
    }

    function updateSelectionUi() {
        const count = selectedRowIds.size;
        const selectedEl = document.getElementById('dfasSelectedCount');
        const applySelectedBtn = document.getElementById('dfasApplySelectedBtn');
        if (selectedEl) selectedEl.textContent = String(count);
        if (applySelectedBtn) applySelectedBtn.disabled = count === 0;
        syncSelectAllCheckbox();
    }

    function updateMatchedCountUi(count) {
        matchedCount = count;
        const matchedEl = document.getElementById('dfasMatchedCount');
        const applyAllBtn = document.getElementById('dfasApplyAllBtn');
        const label = document.getElementById('dfasMatchedCountLabel');
        if (matchedEl) matchedEl.textContent = String(count);
        if (applyAllBtn) {
            applyAllBtn.disabled = count === 0;
            applyAllBtn.textContent = 'Apply All Matched (' + count + ')';
        }
        if (label) {
            label.innerHTML = '<span id="dfasMatchedCount">' + count + '</span> row' +
                (count === 1 ? '' : 's') + ' ready to apply';
        }
    }

    function updateStatusBadges(statusCounts) {
        if (!statusCounts) return;
        document.querySelectorAll('.dfas-import-page .badge').forEach(function () {
            // Status badges are server-rendered; patch known keys via data attributes would be ideal,
            // but we update the sticky matched count and imported badge if present.
        });
        const imported = statusCounts.imported || 0;
        const badgeBar = document.querySelector('.dfas-import-page .d-flex.flex-wrap.gap-2.mb-3');
        if (!badgeBar) return;
        let importedBadge = badgeBar.querySelector('[data-dfas-status="imported"]');
        if (imported > 0) {
            if (!importedBadge) {
                importedBadge = document.createElement('span');
                importedBadge.className = 'badge bg-success';
                importedBadge.dataset.dfasStatus = 'imported';
                badgeBar.appendChild(importedBadge);
            }
            importedBadge.textContent = 'Imported: ' + imported;
        } else if (importedBadge) {
            importedBadge.remove();
        }
    }

    function markRowImported(rowId, paymentHistoryId) {
        const tr = document.querySelector('tr[data-row-id="' + rowId + '"]');
        if (!tr) return;

        tr.classList.remove('dfas-row-matched');
        tr.classList.add('dfas-row-imported');

        const statusTd = tr.querySelector('td:first-child');
        if (statusTd) {
            statusTd.innerHTML = '<span class="badge bg-success">Imported</span>';
        }

        const actionsTd = tr.querySelector('td:last-child');
        if (actionsTd) {
            let html = '<span class="text-success" title="Imported">✓</span>';
            if (paymentHistoryId) {
                html += '<span class="small text-body-secondary ms-1">PH #' +
                    escapeHtml(paymentHistoryId) + '</span>';
            }
            actionsTd.innerHTML = html;
        }

        selectedRowIds.delete(String(rowId));
        const cb = document.getElementById('im-' + rowId);
        if (cb) cb.remove();
        updateSelectionUi();
    }

    // ── Apply rows ──────────────────────────────────────────────────────────
    async function applyRows(rowIds) {
        const url = applyRowsUrl();
        if (!url) {
            alert('Could not apply: missing apply URL.');
            return;
        }
        const ids = Array.from(new Set(rowIds.map(String)));
        if (!ids.length) return;

        const response = await fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({ row_ids: ids.map(Number) }),
        });

        let data = {};
        try {
            data = await response.json();
        } catch (e) {
            alert('Could not apply: invalid response.');
            return;
        }

        if (!response.ok || !data.success) {
            alert('Could not apply: ' + (data.message || 'Unknown error'));
            return;
        }

        const details = data.applied_details || {};
        (data.applied || []).forEach(function (rowId) {
            const info = details[rowId] || {};
            markRowImported(rowId, info.payment_history_id);
        });

        if (data.failed && Object.keys(data.failed).length) {
            const lines = Object.entries(data.failed)
                .map(function (entry) { return 'Row ' + entry[0] + ': ' + entry[1]; });
            alert('Some rows could not be applied:\n' + lines.join('\n'));
        }

        updateMatchedCountUi(data.matched_count != null ? data.matched_count : matchedCount);
        updateStatusBadges(data.status_counts);
    }

    async function closeBatch(force) {
        const url = closeBatchUrl();
        if (!url) {
            alert('Could not close batch: missing URL.');
            return;
        }

        const response = await fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({ force: !!force }),
        });

        let data = {};
        try {
            data = await response.json();
        } catch (e) {
            alert('Could not close batch: invalid response.');
            return;
        }

        if (response.status === 400 && !force) {
            if (confirm(data.message || 'Unresolved rows remain. Close anyway?')) {
                return closeBatch(true);
            }
            return;
        }

        if (!response.ok || !data.success) {
            alert('Could not close batch: ' + (data.message || 'Unknown error'));
            return;
        }

        if (data.redirect_url) {
            window.location.href = data.redirect_url;
        }
    }

    // ── Match preview ─────────────────────────────────────────────────────────
    async function openMatchPreview(rowId) {
        const url = rowPreviewUrl(rowId);
        if (!url) {
            alert('Could not load preview: missing URL.');
            return;
        }

        const response = await fetch(url, { credentials: 'same-origin' });
        let data = {};
        try {
            data = await response.json();
        } catch (e) {
            alert('Could not load preview: invalid response.');
            return;
        }

        if (!response.ok || !data.success) {
            alert('Could not load preview: ' + (data.message || 'Unknown error'));
            return;
        }

        const setText = function (id, text) {
            const el = document.getElementById(id);
            if (el) el.textContent = text || '—';
        };

        setText('dfasPreviewContract', data.contract_number);
        const meta = [data.contract_type, data.contract_status].filter(Boolean).join(' · ');
        setText('dfasPreviewContractMeta', meta || '—');

        const idiqEl = document.getElementById('dfasPreviewIdiq');
        if (idiqEl) {
            if (data.idiq_number) {
                idiqEl.innerHTML = '<span class="font-monospace">' +
                    escapeHtml(data.idiq_number) + '</span>' +
                    ' <span class="fst-italic text-body-secondary">(informational only)</span>';
            } else {
                idiqEl.innerHTML = '<span class="text-body-secondary fst-italic">None (informational only)</span>';
            }
        }

        let clinText = '—';
        if (data.clin_item_number) {
            clinText = data.clin_item_number;
            if (data.clin_item_type) clinText += ' (' + data.clin_item_type + ')';
            if (data.clin_item_value != null) {
                clinText += ' — Item ' + fmtMoney(data.clin_item_value);
            }
        }
        setText('dfasPreviewClin', clinText);

        let shipText = '—';
        if (data.shipment_name) {
            shipText = data.shipment_name;
            const parts = [];
            if (data.shipment_item_value != null) {
                parts.push('Item ' + fmtMoney(data.shipment_item_value));
            }
            if (data.shipment_wawf_payment != null) {
                parts.push('Cust. Pay ' + fmtMoney(data.shipment_wawf_payment));
            }
            if (parts.length) shipText += ' — ' + parts.join(', ');
        }
        setText('dfasPreviewShipment', shipText);

        setText('dfasPreviewDfasAmount', fmtMoney(data.dfas_amount));
        setText('dfasPreviewPaymentDate', data.dfas_payment_date || '—');

        const link = document.getElementById('dfasPreviewOpenContract');
        if (link && data.contract_detail_url) {
            link.href = data.contract_detail_url;
            link.classList.remove('disabled');
        } else if (link) {
            link.href = '#';
            link.classList.add('disabled');
        }

        bootstrap.Modal.getOrCreateInstance(
            document.getElementById('dfasMatchPreviewModal')
        ).show();
    }

    // ── Core resolve POST ─────────────────────────────────────────────────────
    async function resolveRow(rowId, payload) {
        const url = rowResolveUrl(rowId);
        if (!url) {
            alert('Could not save: missing resolve URL.');
            return;
        }
        const response = await fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify(payload),
        });
        let data = {};
        try {
            data = await response.json();
        } catch (e) {
            alert('Could not save: invalid response.');
            return;
        }
        if (!response.ok || !data.success) {
            alert('Could not save: ' + (data.message || 'Unknown error'));
            return;
        }
        window.location.reload();
    }

    // ── Resolve Modal ─────────────────────────────────────────────────────────
    function openResolveModal(btn) {
        const tr = btn.closest('tr[data-row-id]');
        const rowId = tr.dataset.rowId;
        const startStep = btn.dataset.startStep || 'contract';

        resolveState.rowId = rowId;
        resolveState.steps = ['contract', 'clin', 'shipment'];
        resolveState.currentStepIndex = Math.max(
            0,
            resolveState.steps.indexOf(startStep)
        );
        resolveState.contractId = btn.dataset.contractId || null;
        resolveState.clinId = btn.dataset.clinId || null;
        resolveState.shipmentId = btn.dataset.shipmentId || null;
        resolveState.clinHasShipments = !!resolveState.shipmentId;
        resolveState.rowRef = btn.dataset.rowRef || '';
        _preloadedShipments = null;

        const rowRefEl = document.getElementById('dfasResolveRowRef');
        if (rowRefEl) rowRefEl.textContent = resolveState.rowRef;

        const amount = btn.dataset.amount || '';
        const date = btn.dataset.date || '';
        const fmtAmount = amount
            ? '$' + parseFloat(amount).toLocaleString('en-US',
                { minimumFractionDigits: 2, maximumFractionDigits: 2 })
            : '';
        const metaParts = [fmtAmount, date].filter(Boolean);
        const metaEl = document.getElementById('dfasResolveRowMeta');
        if (metaEl) metaEl.textContent = metaParts.join('    ');

        renderStepNav();
        showResolveStep(resolveState.steps[resolveState.currentStepIndex]);

        if (resolveState.contractId) {
            loadClins(resolveState.contractId, resolveState.clinId);
        }
        if (resolveState.clinId) {
            loadShipments(resolveState.clinId, false, resolveState.shipmentId);
        }

        bootstrap.Modal.getOrCreateInstance(
            document.getElementById('dfasResolveModal')
        ).show();
    }

    function renderStepNav() {
        const nav = document.getElementById('dfasResolveStepNav');
        if (!nav) return;
        nav.innerHTML = '';
        resolveState.steps.forEach(function (step, i) {
            if (i > 0) {
                const sep = document.createElement('span');
                sep.className = 'text-body-secondary';
                sep.textContent = '›';
                nav.appendChild(sep);
            }
            const span = document.createElement('span');
            span.className = 'dfas-step-item';
            span.dataset.step = step;
            span.textContent = RESOLVE_STEP_LABELS[step];
            nav.appendChild(span);
        });
        updateStepNavState();
    }

    function updateStepNavState() {
        const currentStep = resolveState.steps[resolveState.currentStepIndex];
        document.querySelectorAll('#dfasResolveStepNav .dfas-step-item')
            .forEach(function (el, i) {
                el.classList.remove('dfas-step-active', 'dfas-step-done');
                if (i < resolveState.currentStepIndex) {
                    el.classList.add('dfas-step-done');
                } else if (el.dataset.step === currentStep) {
                    el.classList.add('dfas-step-active');
                }
            });
    }

    function showResolveStep(stepName) {
        document.querySelectorAll('.dfas-resolve-step')
            .forEach(function (el) { el.classList.add('d-none'); });

        const panelId = 'dfasStep' + stepName.charAt(0).toUpperCase() + stepName.slice(1);
        const panel = document.getElementById(panelId);
        if (panel) {
            panel.classList.remove('d-none');
            panel.querySelectorAll('.dfas-resolve-card.is-selected, .list-group-item.active')
                .forEach(function (c) {
                    c.classList.remove('is-selected', 'active');
                });
        }

        const backBtn = document.getElementById('dfasResolveBackBtn');
        if (backBtn) {
            backBtn.style.visibility =
                resolveState.currentStepIndex === 0 ? 'hidden' : 'visible';
        }

        const hasSelection = (
            (stepName === 'contract' && resolveState.contractId) ||
            (stepName === 'clin' && resolveState.clinId) ||
            (stepName === 'shipment' && resolveState.shipmentId)
        );
        updateNextButton(!!hasSelection);

        if (stepName === 'contract' && !resolveState.contractId) {
            const input = document.getElementById('dfasResolveContractInput');
            const results = document.getElementById('dfasResolveContractResults');
            if (input) input.value = '';
            if (results) results.innerHTML = '';
        }

        updateStepNavState();
    }

    function updateNextButton(hasSelection) {
        const btn = document.getElementById('dfasResolveNextBtn');
        if (!btn) return;
        const isLastStep =
            resolveState.currentStepIndex === resolveState.steps.length - 1;
        const currentStep = resolveState.steps[resolveState.currentStepIndex];
        const effectivelyLast = isLastStep ||
            (currentStep === 'clin' &&
             resolveState.clinId &&
             !resolveState.clinHasShipments);

        btn.disabled = !hasSelection;
        btn.textContent = effectivelyLast ? 'Assign' : 'Next ›';
    }

    function initContractSearch() {
        const input = document.getElementById('dfasResolveContractInput');
        if (!input) return;

        let debounce;
        input.addEventListener('input', function () {
            clearTimeout(debounce);
            const q = this.value.trim();
            const results = document.getElementById('dfasResolveContractResults');
            if (!results) return;
            if (q.length < 3) { results.innerHTML = ''; return; }

            debounce = setTimeout(function () {
                const searchUrl = window.DFAS_CONTRACT_SEARCH_URL || '/contracts/search/';
                fetch(searchUrl + '?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        results.innerHTML = '';
                        const list = data.results || data;
                        if (!list.length) {
                            results.innerHTML =
                                '<div class="list-group-item text-body-secondary small">No results.</div>';
                            return;
                        }
                        list.forEach(function (contract) {
                            const item = document.createElement('button');
                            item.type = 'button';
                            item.className = 'list-group-item list-group-item-action ' +
                                'd-flex justify-content-between align-items-center';
                            item.dataset.contractId = contract.id;
                            item.dataset.contractNumber = contract.contract_number;

                            const poLine = contract.po_numbers && contract.po_numbers.length
                                ? '<div class="small text-body-secondary">PO: ' +
                                  contract.po_numbers.map(escapeHtml).join(', ') + '</div>'
                                : '';

                            item.innerHTML =
                                '<div>' +
                                '<span class="font-monospace fw-semibold small">' +
                                    escapeHtml(contract.contract_number || '') +
                                '</span>' +
                                poLine +
                                '</div>' +
                                '<span class="badge bg-secondary">' +
                                    escapeHtml(contract.status || '') +
                                '</span>';

                            if (resolveState.contractId &&
                                String(contract.id) === String(resolveState.contractId)) {
                                item.classList.add('active');
                            }

                            item.addEventListener('click', function () {
                                results.querySelectorAll('.active')
                                    .forEach(function (el) { el.classList.remove('active'); });
                                item.classList.add('active');
                                resolveState.contractId = String(contract.id);
                                resolveState.clinId = null;
                                resolveState.shipmentId = null;
                                resolveState.clinHasShipments = false;
                                _preloadedShipments = null;
                                updateNextButton(true);
                            });
                            results.appendChild(item);
                        });
                    })
                    .catch(function () {
                        results.innerHTML =
                            '<div class="list-group-item text-danger small">Search failed.</div>';
                    });
            }, 280);
        });
    }

    function loadClins(contractId, preselectClinId) {
        const loading = document.getElementById('dfasStepClinLoading');
        const grid = document.getElementById('dfasStepClinCards');
        if (!loading || !grid) return;
        loading.classList.remove('d-none');
        grid.innerHTML = '';

        const clinsUrl = window.DFAS_CLINS_API_URL || '/contracts/dfas-imports/api/clins/';
        fetch(clinsUrl + '?contract_id=' + contractId, { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                loading.classList.add('d-none');
                const clins = data.clins || [];
                if (!clins.length) {
                    grid.innerHTML = '<div class="col text-body-secondary small">No CLINs found on this contract.</div>';
                    return;
                }
                clins.forEach(function (clin) {
                    const col = document.createElement('div');
                    col.className = 'col-6 col-md-4';
                    const fmtVal = function (v) {
                        return v != null
                            ? '$' + parseFloat(v).toLocaleString('en-US',
                                { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                            : '';
                    };
                    col.innerHTML =
                        '<div class="card h-100 dfas-resolve-card"' +
                            ' role="button" tabindex="0"' +
                            ' data-clin-id="' + clin.id + '"' +
                            ' data-has-shipments="' + clin.has_shipments + '">' +
                            '<div class="card-body p-3">' +
                                '<div class="fw-semibold font-monospace fs-6">' + escapeHtml(clin.item_number) + '</div>' +
                                '<div class="text-body-secondary small">' + escapeHtml(clin.item_type_display || '') + '</div>' +
                                '<hr class="my-2">' +
                                '<div class="small">' +
                                    '<div class="d-flex justify-content-between">' +
                                        '<span class="text-body-secondary">Item</span>' +
                                        '<span class="fw-semibold">' + escapeHtml(fmtVal(clin.item_value)) + '</span>' +
                                    '</div>' +
                                    '<div class="d-flex justify-content-between">' +
                                        '<span class="text-body-secondary">Quote</span>' +
                                        '<span>' + escapeHtml(fmtVal(clin.quote_value)) + '</span>' +
                                    '</div>' +
                                '</div>' +
                            '</div>' +
                        '</div>';

                    const card = col.querySelector('.dfas-resolve-card');
                    if (preselectClinId && String(clin.id) === String(preselectClinId)) {
                        card.classList.add('is-selected');
                        resolveState.clinId = String(clin.id);
                        resolveState.clinHasShipments = clin.has_shipments;
                        updateNextButton(true);
                    }

                    card.addEventListener('click', function () {
                        grid.querySelectorAll('.dfas-resolve-card')
                            .forEach(function (c) { c.classList.remove('is-selected'); });
                        card.classList.add('is-selected');
                        resolveState.clinId = String(clin.id);
                        resolveState.clinHasShipments = clin.has_shipments;
                        resolveState.shipmentId = null;
                        updateNextButton(true);

                        if (clin.has_shipments) {
                            loadShipments(clin.id, true);
                        }
                    });
                    grid.appendChild(col);
                });
            })
            .catch(function () {
                loading.classList.add('d-none');
                grid.innerHTML =
                    '<div class="col text-danger small">Failed to load CLINs.</div>';
            });
    }

    function loadShipments(clinId, preloadOnly, preselectShipmentId) {
        _preloadedShipments = null;
        const loading = document.getElementById('dfasStepShipmentLoading');
        const grid = document.getElementById('dfasStepShipmentCards');

        if (!preloadOnly && loading && grid) {
            loading.classList.remove('d-none');
            grid.innerHTML = '';
        }

        const shipmentsUrl = window.DFAS_SHIPMENTS_API_URL || '/contracts/dfas-imports/api/shipments/';
        fetch(shipmentsUrl + '?clin_id=' + clinId, { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                _preloadedShipments = data;
                if (preloadOnly) return;
                if (loading) loading.classList.add('d-none');
                if (grid) renderShipmentCards(data, grid, preselectShipmentId);
            })
            .catch(function () {
                if (!preloadOnly) {
                    if (loading) loading.classList.add('d-none');
                    if (grid) {
                        grid.innerHTML =
                            '<div class="col text-danger small">Failed to load shipments.</div>';
                    }
                }
            });
    }

    function renderShipmentCards(data, grid, preselectShipmentId) {
        const shipments = data.shipments || [];
        if (!shipments.length) {
            grid.innerHTML = '<div class="col text-body-secondary small">No shipments found on this CLIN.</div>';
            return;
        }
        shipments.forEach(function (ship) {
            const col = document.createElement('div');
            col.className = 'col-6 col-md-4';
            const fmtVal = function (v) {
                return v != null
                    ? '$' + parseFloat(v).toLocaleString('en-US',
                        { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                    : '';
            };

            const shipDateRow = ship.ship_date
                ? '<div class="d-flex justify-content-between">' +
                      '<span class="text-body-secondary">Shipped</span>' +
                      '<span>' + escapeHtml(ship.ship_date) + '</span>' +
                  '</div>'
                : '';

            col.innerHTML =
                '<div class="card h-100 dfas-resolve-card"' +
                    ' role="button" tabindex="0"' +
                    ' data-shipment-id="' + ship.id + '">' +
                    '<div class="card-body p-3">' +
                        '<div class="fw-semibold">' + escapeHtml(ship.display_name) + '</div>' +
                        '<hr class="my-2">' +
                        '<div class="small">' +
                            '<div class="d-flex justify-content-between">' +
                                '<span class="text-body-secondary">Item</span>' +
                                '<span class="fw-semibold">' + escapeHtml(fmtVal(ship.item_value)) + '</span>' +
                            '</div>' +
                            '<div class="d-flex justify-content-between">' +
                                '<span class="text-body-secondary">Quote</span>' +
                                '<span>' + escapeHtml(fmtVal(ship.quote_value)) + '</span>' +
                            '</div>' +
                            '<div class="d-flex justify-content-between">' +
                                '<span class="text-body-secondary">Paid</span>' +
                                '<span>' + escapeHtml(fmtVal(ship.paid_amount)) + '</span>' +
                            '</div>' +
                            shipDateRow +
                        '</div>' +
                    '</div>' +
                '</div>';

            const card = col.querySelector('.dfas-resolve-card');
            if (preselectShipmentId && String(ship.id) === String(preselectShipmentId)) {
                card.classList.add('is-selected');
                resolveState.shipmentId = String(ship.id);
                updateNextButton(true);
            }

            card.addEventListener('click', function () {
                grid.querySelectorAll('.dfas-resolve-card')
                    .forEach(function (c) { c.classList.remove('is-selected'); });
                card.classList.add('is-selected');
                resolveState.shipmentId = String(ship.id);
                updateNextButton(true);
            });
            grid.appendChild(col);
        });
    }

    function initResolveModalButtons() {
        document.getElementById('dfasResolveBackBtn')
            ?.addEventListener('click', function () {
                if (resolveState.currentStepIndex > 0) {
                    resolveState.currentStepIndex--;
                    const step = resolveState.steps[resolveState.currentStepIndex];
                    if (step === 'clin') {
                        resolveState.clinId = null;
                        resolveState.clinHasShipments = false;
                        resolveState.shipmentId = null;
                        _preloadedShipments = null;
                    }
                    if (step === 'contract') {
                        resolveState.contractId = null;
                        resolveState.clinId = null;
                        resolveState.clinHasShipments = false;
                        resolveState.shipmentId = null;
                        _preloadedShipments = null;
                    }
                    showResolveStep(step);
                }
            });

        document.getElementById('dfasResolveNextBtn')
            ?.addEventListener('click', function () {
                const currentStep = resolveState.steps[resolveState.currentStepIndex];
                const isLastStep =
                    resolveState.currentStepIndex === resolveState.steps.length - 1;
                const effectivelyLast = isLastStep ||
                    (currentStep === 'clin' && !resolveState.clinHasShipments);

                if (effectivelyLast) {
                    submitResolve();
                } else {
                    resolveState.currentStepIndex++;
                    const nextStep = resolveState.steps[resolveState.currentStepIndex];

                    if (nextStep === 'clin' && resolveState.contractId) {
                        loadClins(resolveState.contractId, resolveState.clinId);
                    }
                    if (nextStep === 'shipment' && resolveState.clinId) {
                        const grid = document.getElementById('dfasStepShipmentCards');
                        const loading = document.getElementById('dfasStepShipmentLoading');
                        if (_preloadedShipments) {
                            if (grid) {
                                grid.innerHTML = '';
                                renderShipmentCards(
                                    _preloadedShipments,
                                    grid,
                                    resolveState.shipmentId
                                );
                            }
                        } else {
                            loadShipments(resolveState.clinId, false, resolveState.shipmentId);
                        }
                    }

                    showResolveStep(nextStep);
                }
            });
    }

    function submitResolve() {
        const payload = {
            action: 'resolve_unified',
            clin_id: resolveState.clinId,
        };
        if (resolveState.contractId) {
            payload.contract_id = resolveState.contractId;
        }
        if (resolveState.shipmentId) {
            payload.shipment_id = resolveState.shipmentId;
        }

        resolveRow(resolveState.rowId, payload);
        bootstrap.Modal.getOrCreateInstance(
            document.getElementById('dfasResolveModal')
        ).hide();
    }

    function initCheckboxHandlers() {
        document.addEventListener('change', function (event) {
            const target = event.target;
            if (target.id === 'dfasSelectAllMatched') {
                const checked = target.checked;
                getMatchedCheckboxes().forEach(function (cb) {
                    cb.checked = checked;
                    if (checked) {
                        selectedRowIds.add(cb.value);
                    } else {
                        selectedRowIds.delete(cb.value);
                    }
                });
                updateSelectionUi();
                return;
            }
            if (target.classList.contains('dfas-row-checkbox')) {
                if (target.checked) {
                    selectedRowIds.add(target.value);
                } else {
                    selectedRowIds.delete(target.value);
                }
                updateSelectionUi();
            }
        });

        document.getElementById('dfasApplySelectedBtn')
            ?.addEventListener('click', function () {
                applyRows(Array.from(selectedRowIds));
            });

        document.getElementById('dfasApplyAllBtn')
            ?.addEventListener('click', function () {
                const ids = getMatchedCheckboxes().map(function (cb) { return cb.value; });
                applyRows(ids);
            });

        document.getElementById('dfasCloseBatchBtn')
            ?.addEventListener('click', function () {
                closeBatch(false);
            });
    }

    // ── Delegated click handler ───────────────────────────────────────────────
    document.addEventListener('click', async function (event) {
        const btn = event.target.closest('[data-action]');
        if (!btn) return;

        const action = btn.dataset.action;
        const rowEl = btn.closest('[data-row-id]');
        const rowId = rowEl ? rowEl.dataset.rowId : btn.dataset.rowId;

        switch (action) {
            case 'open_resolve_modal':
                openResolveModal(btn);
                break;

            case 'preview_match':
                if (rowId) openMatchPreview(rowId);
                break;

            case 'apply_row':
                if (btn.dataset.rowId) {
                    await applyRows([btn.dataset.rowId]);
                }
                break;

            case 'skip':
            case 'unskip':
            case 'import_anyway':
                if (rowId) await resolveRow(rowId, { action: action });
                break;

            default:
                break;
        }
    });

    document.addEventListener('DOMContentLoaded', function () {
        const matchedEl = document.getElementById('dfasMatchedCount');
        if (matchedEl) matchedCount = parseInt(matchedEl.textContent, 10) || 0;

        initContractSearch();
        initResolveModalButtons();
        initCheckboxHandlers();
        updateSelectionUi();
    });
})();
