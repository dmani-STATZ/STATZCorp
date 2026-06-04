/**
 * DFAS import review: per-row resolution via unified drill-down resolve modal.
 * Requires {% csrf_token %}, #dfasResolveRowUrlZero (URL with row_id=0),
 * window.DFAS_CONTRACT_SEARCH_URL, window.DFAS_CLINS_API_URL,
 * window.DFAS_SHIPMENTS_API_URL.
 */
(function () {
    'use strict';

    // ── Unified Resolve Modal state ──────────────────────────────────────────
    const resolveState = {
        rowId: null,
        steps: [],            // subset of ['contract','clin','shipment'] for this row
        currentStepIndex: 0,
        contractId: null,
        clinId: null,
        clinHasShipments: false,
        shipmentId: null,
        rowRef: '',
    };

    const RESOLVE_STEP_LABELS = {
        contract: 'Contract',
        clin: 'CLIN',
        shipment: 'Shipment',
    };

    let _preloadedShipments = null; // cache from background preload

    // ── Utilities ─────────────────────────────────────────────────────────────
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

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, function (c) {
            return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
        });
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
        const startStep = btn.dataset.startStep; // 'contract'|'clin'|'shipment'

        // Reset state
        resolveState.rowId = rowId;
        resolveState.contractId = btn.dataset.contractId || null;
        resolveState.clinId = btn.dataset.clinId || null;
        resolveState.clinHasShipments = false;
        resolveState.shipmentId = null;
        resolveState.rowRef = btn.dataset.rowRef || '';
        _preloadedShipments = null;

        // Build steps array from startStep
        const allSteps = ['contract', 'clin', 'shipment'];
        resolveState.steps = allSteps.slice(allSteps.indexOf(startStep));
        resolveState.currentStepIndex = 0;

        // Populate row reference in modal header
        const rowRefEl = document.getElementById('dfasResolveRowRef');
        if (rowRefEl) rowRefEl.textContent = resolveState.rowRef;

        // Render step breadcrumb
        renderStepNav();

        // Show the first step
        showResolveStep(resolveState.steps[0]);

        // If starting at clin step, preload CLINs immediately
        if (startStep === 'clin' && resolveState.contractId) {
            loadClins(resolveState.contractId);
        }

        // If starting at shipment step, preload shipments immediately
        if (startStep === 'shipment' && resolveState.clinId) {
            loadShipments(resolveState.clinId);
        }

        // Open the modal
        bootstrap.Modal.getOrCreateInstance(
            document.getElementById('dfasResolveModal')
        ).show();
    }

    // ── Step rendering helpers ────────────────────────────────────────────────
    function renderStepNav() {
        const nav = document.getElementById('dfasResolveStepNav');
        if (!nav) return;
        nav.innerHTML = '';
        resolveState.steps.forEach((step, i) => {
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
            .forEach((el, i) => {
                el.classList.remove('dfas-step-active', 'dfas-step-done');
                if (i < resolveState.currentStepIndex) {
                    el.classList.add('dfas-step-done');
                } else if (el.dataset.step === currentStep) {
                    el.classList.add('dfas-step-active');
                }
            });
    }

    function showResolveStep(stepName) {
        // Hide all step panels
        document.querySelectorAll('.dfas-resolve-step')
            .forEach(el => el.classList.add('d-none'));

        // Show target panel
        const panelId = 'dfasStep' + stepName.charAt(0).toUpperCase() + stepName.slice(1);
        const panel = document.getElementById(panelId);
        if (panel) {
            panel.classList.remove('d-none');
            // Reset selections in this step
            panel.querySelectorAll('.dfas-resolve-card.is-selected')
                .forEach(c => c.classList.remove('is-selected'));
        }

        // Back button: hidden if on first step, visible otherwise
        const backBtn = document.getElementById('dfasResolveBackBtn');
        if (backBtn) {
            backBtn.style.visibility =
                resolveState.currentStepIndex === 0 ? 'hidden' : 'visible';
        }

        // Next button: disabled (no selection yet), label based on position
        updateNextButton(false);

        // Clear contract search if re-entering step 1
        if (stepName === 'contract') {
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

        // On CLIN step: if selected CLIN has no shipments, treat as last step
        const currentStep = resolveState.steps[resolveState.currentStepIndex];
        const effectivelyLast = isLastStep ||
            (currentStep === 'clin' &&
             resolveState.clinId &&
             !resolveState.clinHasShipments);

        btn.disabled = !hasSelection;
        btn.textContent = effectivelyLast ? 'Assign' : 'Next ›';
    }

    // ── Contract search (Step 1) ──────────────────────────────────────────────
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

            debounce = setTimeout(() => {
                const searchUrl = window.DFAS_CONTRACT_SEARCH_URL || '/contracts/search/';
                fetch(searchUrl + '?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
                    .then(r => r.json())
                    .then(data => {
                        results.innerHTML = '';
                        const list = data.results || data;
                        if (!list.length) {
                            results.innerHTML =
                                '<div class="list-group-item text-body-secondary small">No results.</div>';
                            return;
                        }
                        list.forEach(contract => {
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

                            item.addEventListener('click', () => {
                                // Deselect others
                                results.querySelectorAll('.active')
                                    .forEach(el => el.classList.remove('active'));
                                item.classList.add('active');
                                resolveState.contractId = String(contract.id);
                                updateNextButton(true);
                            });
                            results.appendChild(item);
                        });
                    })
                    .catch(() => {
                        results.innerHTML =
                            '<div class="list-group-item text-danger small">Search failed.</div>';
                    });
            }, 280);
        });
    }

    // ── CLIN loader ───────────────────────────────────────────────────────────
    function loadClins(contractId) {
        const loading = document.getElementById('dfasStepClinLoading');
        const grid = document.getElementById('dfasStepClinCards');
        if (!loading || !grid) return;
        loading.classList.remove('d-none');
        grid.innerHTML = '';

        const clinsUrl = window.DFAS_CLINS_API_URL || '/contracts/dfas-imports/api/clins/';
        fetch(clinsUrl + '?contract_id=' + contractId, { credentials: 'same-origin' })
            .then(r => r.json())
            .then(data => {
                loading.classList.add('d-none');
                const clins = data.clins || [];
                if (!clins.length) {
                    grid.innerHTML = '<div class="col text-body-secondary small">No CLINs found on this contract.</div>';
                    return;
                }
                clins.forEach(clin => {
                    const col = document.createElement('div');
                    col.className = 'col-6 col-md-4';
                    const fmtVal = v => v != null
                        ? '$' + parseFloat(v).toLocaleString('en-US',
                            { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                        : '';
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

                    col.querySelector('.dfas-resolve-card').addEventListener('click', () => {
                        grid.querySelectorAll('.dfas-resolve-card')
                            .forEach(c => c.classList.remove('is-selected'));
                        col.querySelector('.dfas-resolve-card').classList.add('is-selected');
                        resolveState.clinId = String(clin.id);
                        resolveState.clinHasShipments = clin.has_shipments;
                        updateNextButton(true);

                        // Preload shipments in background if CLIN has them
                        if (clin.has_shipments) {
                            loadShipments(clin.id, /* preloadOnly */ true);
                        }
                    });
                    grid.appendChild(col);
                });
            })
            .catch(() => {
                loading.classList.add('d-none');
                grid.innerHTML =
                    '<div class="col text-danger small">Failed to load CLINs.</div>';
            });
    }

    // ── Shipment loader ───────────────────────────────────────────────────────
    function loadShipments(clinId, preloadOnly = false) {
        _preloadedShipments = null;
        const loading = document.getElementById('dfasStepShipmentLoading');
        const grid = document.getElementById('dfasStepShipmentCards');

        if (!preloadOnly && loading && grid) {
            loading.classList.remove('d-none');
            grid.innerHTML = '';
        }

        const shipmentsUrl = window.DFAS_SHIPMENTS_API_URL || '/contracts/dfas-imports/api/shipments/';
        fetch(shipmentsUrl + '?clin_id=' + clinId, { credentials: 'same-origin' })
            .then(r => r.json())
            .then(data => {
                _preloadedShipments = data;
                if (preloadOnly) return; // just cache it, don't render yet
                if (loading) loading.classList.add('d-none');
                if (grid) renderShipmentCards(data, grid);
            })
            .catch(() => {
                if (!preloadOnly) {
                    if (loading) loading.classList.add('d-none');
                    if (grid) grid.innerHTML =
                        '<div class="col text-danger small">Failed to load shipments.</div>';
                }
            });
    }

    function renderShipmentCards(data, grid) {
        const shipments = data.shipments || [];
        if (!shipments.length) {
            grid.innerHTML = '<div class="col text-body-secondary small">No shipments found on this CLIN.</div>';
            return;
        }
        shipments.forEach(ship => {
            const col = document.createElement('div');
            col.className = 'col-6 col-md-4';
            const fmtVal = v => v != null
                ? '$' + parseFloat(v).toLocaleString('en-US',
                    { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                : '';

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

            col.querySelector('.dfas-resolve-card').addEventListener('click', () => {
                grid.querySelectorAll('.dfas-resolve-card')
                    .forEach(c => c.classList.remove('is-selected'));
                col.querySelector('.dfas-resolve-card').classList.add('is-selected');
                resolveState.shipmentId = String(ship.id);
                updateNextButton(true);
            });
            grid.appendChild(col);
        });
    }

    // ── Back and Next/Assign button handlers ─────────────────────────────────
    function initResolveModalButtons() {
        document.getElementById('dfasResolveBackBtn')
            ?.addEventListener('click', () => {
                if (resolveState.currentStepIndex > 0) {
                    resolveState.currentStepIndex--;
                    // Clear forward state for the step we're returning to
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
            ?.addEventListener('click', () => {
                const currentStep = resolveState.steps[resolveState.currentStepIndex];
                const isLastStep =
                    resolveState.currentStepIndex === resolveState.steps.length - 1;
                const effectivelyLast = isLastStep ||
                    (currentStep === 'clin' && !resolveState.clinHasShipments);

                if (effectivelyLast) {
                    submitResolve();
                } else {
                    // Advance to next step
                    resolveState.currentStepIndex++;
                    const nextStep = resolveState.steps[resolveState.currentStepIndex];

                    // Load data for next step if needed
                    if (nextStep === 'clin' && resolveState.contractId) {
                        loadClins(resolveState.contractId);
                    }
                    if (nextStep === 'shipment' && resolveState.clinId) {
                        // Use preloaded data if available
                        const grid = document.getElementById('dfasStepShipmentCards');
                        const loading = document.getElementById('dfasStepShipmentLoading');
                        if (_preloadedShipments) {
                            if (grid) {
                                grid.innerHTML = '';
                                renderShipmentCards(_preloadedShipments, grid);
                            }
                        } else {
                            loadShipments(resolveState.clinId);
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

    // ── Delegated click handler ───────────────────────────────────────────────
    document.addEventListener('click', async function (event) {
        const btn = event.target.closest('[data-action]');
        if (!btn) return;

        const action = btn.dataset.action;
        const rowEl = btn.closest('[data-row-id]');
        if (!rowEl) return;
        const rowId = rowEl.dataset.rowId;
        if (!rowId) return;

        switch (action) {
            case 'open_resolve_modal':
                openResolveModal(btn);
                break;

            case 'skip':
            case 'unskip':
            case 'import_anyway':
                await resolveRow(rowId, { action: action });
                break;

            default:
                // Unknown action — ignore silently
                break;
        }
    });

    // ── Init on DOMContentLoaded ──────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', function () {
        initContractSearch();
        initResolveModalButtons();
    });
})();
