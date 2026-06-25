/**
 * CLIN Fix Tool (sunset cleanup)
 * ------------------------------
 * Vanilla JS controller for the legacy CLIN reclassification page. The
 * configure pane on the right is a fixed pane (NOT an offcanvas/drawer);
 * its content swaps based on the active row. Every field edit autosaves
 * a draft after a 500ms debounce — there is NO "Stage Changes" button.
 *
 * Scheduled for removal once cleanup completes. Do not couple other
 * features to anything in this module.
 */

// ─── Measure chrome heights for the full-viewport shell ─────────────────
// `.clin-fix-shell` height is `calc(100vh - navbar - footer)`. The values
// are NOT hardcoded so the layout survives navbar/footer height changes
// (branding, etc.). The top navbar in `base_template.html` is `<header
// id="header">`; the bottom contracts footer in `contract_base.html` is
// the only fixed-bottom div on the page. Defaults match the current
// CSS in `app-core.css` (header height: 48px) and an approximate footer
// height; the JS measurement overrides them at runtime.
(function measureChromeHeights() {
    function setVar(name, px) {
        if (px > 0) {
            document.documentElement.style.setProperty(name, px + 'px');
        }
    }
    var headerEl = document.getElementById('header');
    setVar('--clin-fix-navbar-height', headerEl ? headerEl.offsetHeight : 48);

    var footerEl = document.querySelector(
        '.fixed.bottom-0.shadow-lg.border-t'
    );
    setVar('--clin-fix-footer-height', footerEl ? footerEl.offsetHeight : 64);

    // Re-measure on window resize so dynamic content (e.g. badge counts
    // wrapping in the contracts footer) doesn't desync the shell.
    window.addEventListener('resize', function () {
        if (headerEl) {
            setVar('--clin-fix-navbar-height', headerEl.offsetHeight);
        }
        if (footerEl) {
            setVar('--clin-fix-footer-height', footerEl.offsetHeight);
        }
    });
})();

(function () {
    'use strict';

    // ── Helpers ────────────────────────────────────────────────────────
    function $(id) { return document.getElementById(id); }
    function $$(sel, root) {
        return Array.prototype.slice.call((root || document).querySelectorAll(sel));
    }

    function csrfToken() {
        var el = document.querySelector('#csrf-form [name=csrfmiddlewaretoken]');
        return el ? el.value : '';
    }

    function notifyUser(type, message) {
        if (window.notify) {
            window.notify(type, message, 4000);
        } else if (type === 'error') {
            alert(message);
        }
    }

    function debounce(fn, wait) {
        var t;
        return function () {
            var ctx = this, args = arguments;
            clearTimeout(t);
            t = setTimeout(function () { fn.apply(ctx, args); }, wait);
        };
    }

    function fmtCurrency(val) {
        var n = parseFloat(val);
        if (!isFinite(n)) return '—';
        return '$' + n.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    }

    function safeJsonParse(str, fallback) {
        try { return JSON.parse(str); } catch (e) { return fallback; }
    }

    // ── Setup ──────────────────────────────────────────────────────────
    var rootEl = $('clin-fix-root');
    if (!rootEl) return;

    var urls = {
        save: rootEl.dataset.saveUrl,
        draftSave: rootEl.dataset.draftSaveUrl,
        draftDelete: rootEl.dataset.draftDeleteUrl,
        parentOptions: rootEl.dataset.parentOptionsUrl,
    };
    var contractNumber = rootEl.dataset.contractNumber || '';

    /** state[clinId] = { destination_type, staged_data, parent_clin_id, pending_save } */
    var clinFixState = {};
    var activeClinId = null;
    var justSavedSuccessfully = false;

    // Hydrate from server-rendered drafts JSON
    (function seedState() {
        var seed = safeJsonParse(($('clin-fix-existing-drafts') || {}).textContent || '{}', {});
        Object.keys(seed).forEach(function (clinId) {
            var rec = seed[clinId];
            clinFixState[clinId] = {
                destination_type: rec.destination_type,
                staged_data: rec.staged_data || {},
                parent_clin_id: rec.parent_clin_id || null,
                pending_save: false,
            };
        });
    })();

    // Cache row data once per row
    var rowDataCache = {};
    function getRowData(clinId) {
        if (!clinId) return null;
        var key = String(clinId);
        if (rowDataCache[key]) return rowDataCache[key];
        var row = $('clin-fix-row-' + clinId);
        if (!row) return null;
        var ds = row.dataset;
        var record = {
            id: parseInt(clinId, 10),
            row: row,
            itemNumber: ds.itemNumber || '',
            itemValue: parseFloat(ds.itemValue) || 0,
            wawfPayment: parseFloat(ds.wawfPayment) || 0,
            quoteValue: parseFloat(ds.quoteValue) || 0,
            paidAmount: parseFloat(ds.paidAmount) || 0,
            shipQty: ds.shipQty !== '' ? parseFloat(ds.shipQty) : null,
            uom: ds.uom || '',
            supplierId: ds.supplierId !== '' ? parseInt(ds.supplierId, 10) : null,
            supplierName: ds.supplierName || '',
            nsnId: ds.nsnId !== '' ? parseInt(ds.nsnId, 10) : null,
            serialized: safeJsonParse(ds.serialized || '{}', {}),
        };
        rowDataCache[key] = record;
        return record;
    }

    function isStaged(clinId) {
        var s = clinFixState[clinId];
        return !!(s && s.destination_type && s.destination_type !== 'default');
    }

    // ── Pending count + Save All button ────────────────────────────────
    function updatePendingCount() {
        var n = Object.keys(clinFixState).filter(isStaged).length;
        var badge = $('pending-count-badge');
        if (badge) {
            badge.textContent = n + ' conversion' + (n === 1 ? '' : 's') + ' pending';
            badge.className = 'badge ' + (n > 0 ? 'bg-warning text-dark' : 'bg-secondary');
        }
        var saveBtn = $('save-all-btn');
        if (saveBtn) saveBtn.disabled = (n === 0);
    }

    // ── Row visual state ───────────────────────────────────────────────
    function updateRowVisual(clinId) {
        var row = $('clin-fix-row-' + clinId);
        if (!row) return;
        var staged = isStaged(clinId);
        row.classList.toggle('row-staged', staged);
        row.classList.remove('row-error');

        var data = getRowData(clinId);
        var s = clinFixState[clinId];
        var dest = s ? s.destination_type : 'default';

        // Income-side red highlight when staged for a destination that
        // disallows income side (packaging or finance_line).
        var incomeWarn = staged && (dest === 'packaging' || dest === 'finance_line');
        var itemCell = row.querySelector('.js-item-val-cell');
        var wawfCell = row.querySelector('.js-wawf-cell');
        if (itemCell) {
            itemCell.classList.toggle('income-warning', !!(incomeWarn && data && data.itemValue !== 0));
        }
        if (wawfCell) {
            wawfCell.classList.toggle('income-warning', !!(incomeWarn && data && data.wawfPayment !== 0));
        }
    }

    function setActiveRow(clinId) {
        $$('.clin-fix-row.row-active').forEach(function (r) { r.classList.remove('row-active'); });
        if (clinId) {
            var row = $('clin-fix-row-' + clinId);
            if (row) row.classList.add('row-active');
        }
    }

    function setRowParentCleared(clinId, on) {
        var row = $('clin-fix-row-' + clinId);
        if (!row) return;
        row.classList.toggle('row-parent-cleared', !!on);
    }

    function syncDropdownFromState(clinId) {
        var s = clinFixState[clinId];
        var sel = document.querySelector('.clin-fix-destination[data-clin-id="' + clinId + '"]');
        if (!sel) return;
        sel.value = (s && s.destination_type) ? s.destination_type : 'default';
    }

    // ── Autosave indicator ─────────────────────────────────────────────
    var indicatorEl;
    var indicatorTextEl;
    var indicatorTimeout;
    function ensureIndicator() {
        if (!indicatorEl) {
            indicatorEl = $('pane-autosave-indicator');
            indicatorTextEl = $('pane-autosave-text');
        }
    }
    function showSavingIndicator() {
        ensureIndicator();
        if (!indicatorEl) return;
        if (indicatorTimeout) { clearTimeout(indicatorTimeout); indicatorTimeout = null; }
        if (indicatorTextEl) indicatorTextEl.textContent = 'Saving…';
        indicatorEl.classList.add('visible');
    }
    function showSavedIndicator() {
        ensureIndicator();
        if (!indicatorEl) return;
        if (indicatorTextEl) indicatorTextEl.textContent = 'Saved';
        indicatorEl.classList.add('visible');
        if (indicatorTimeout) clearTimeout(indicatorTimeout);
        indicatorTimeout = setTimeout(function () {
            if (indicatorEl) indicatorEl.classList.remove('visible');
        }, 1500);
    }

    // ── Pane state (A: empty, B: default, C: pkg, D: fl, E: ps, F: del)
    function showPaneState(stateLetter) {
        $$('#configure-pane [data-pane-state]').forEach(function (el) {
            el.style.display = (el.getAttribute('data-pane-state') === stateLetter) ? '' : 'none';
        });
    }

    function setPaneTitle(text) {
        var t = $('pane-title');
        if (t) t.textContent = text;
    }

    // ── Pane fillers ───────────────────────────────────────────────────
    function fillDefaultPanel(data) {
        var dl = $('pane-default-fields');
        if (!dl) return;
        var entries = [
            ['Item #', data.itemNumber || '—'],
            ['Type', data.serialized.item_type_display || '—'],
            ['Supplier', data.supplierName || '—'],
            ['NSN', data.serialized.nsn_code || '—'],
            ['Order Qty', (data.serialized.order_qty != null) ? (data.serialized.order_qty + (data.uom || '')) : '—'],
            ['Item Value', data.itemValue ? fmtCurrency(data.itemValue) : '—'],
            ['Quote Value', data.quoteValue ? fmtCurrency(data.quoteValue) : '—'],
            ['Paid Amount', data.paidAmount ? fmtCurrency(data.paidAmount) : '—'],
            ['WAWF Payment', data.wawfPayment ? fmtCurrency(data.wawfPayment) : '—'],
            ['Ship Date', data.serialized.ship_date || '—'],
            ['POD Date', data.serialized.pod_date || '—'],
        ];
        dl.innerHTML = entries.map(function (e) {
            return '<dt class="col-5 text-muted">' + e[0] + '</dt>' +
                   '<dd class="col-7">' + e[1] + '</dd>';
        }).join('');
    }

    function fillPackagingForm(data) {
        var s = clinFixState[data.id] || { destination_type: 'packaging', staged_data: {} };
        var staged = s.staged_data || {};
        $('pkg-packhouse').value = data.supplierName || '(none)';
        $('pkg-quote').value = ('quote_amount' in staged ? staged.quote_amount
                                : (data.serialized.quote_value || '')) || '';
        $('pkg-paid').value = ('amount_paid' in staged ? staged.amount_paid
                               : (data.serialized.paid_amount || '')) || '';
        $('pkg-payment-date').value = staged.payment_date || data.serialized.paid_date || '';
        $('pkg-invoice').value = staged.invoice_number || '';

        var today = new Date().toISOString().slice(0, 10);
        var itemTypeDisplay = data.serialized.item_type_display || 'None';
        var defaultNote = 'Migrated from CLIN ' + data.itemNumber + ' on ' + today
                        + '. Original item_type: ' + (itemTypeDisplay || 'None') + '.';
        $('pkg-notes').value = ('notes' in staged && staged.notes !== null && staged.notes !== undefined)
            ? staged.notes : defaultNote;

        var warn = $('pkg-income-warning');
        if (warn) {
            if (data.itemValue || data.wawfPayment) {
                warn.style.display = 'block';
                warn.textContent = 'This CLIN has non-zero Item Value or WAWF Payment. ' +
                    'Packaging entries must have no income side. The server will block this conversion.';
            } else {
                warn.style.display = 'none';
            }
        }
    }

    function fillFinanceLineForm(data) {
        var s = clinFixState[data.id] || { destination_type: 'finance_line', staged_data: {} };
        var staged = s.staged_data || {};
        var sel = $('fl-line-type');
        var lineType = staged.line_type || 'Trucking';
        var preset = ['Trucking', 'Freight', 'Labels', 'Miscellaneous'];
        if (preset.indexOf(lineType) >= 0) {
            sel.value = lineType;
            $('fl-line-type-other-wrap').style.display = 'none';
            $('fl-line-type-other').value = '';
        } else {
            sel.value = 'Other';
            $('fl-line-type-other-wrap').style.display = 'block';
            $('fl-line-type-other').value = lineType || '';
        }

        var supplierLabel = data.supplierName || 'None';
        var typeLabel = data.serialized.item_type_display || '';
        var defaultDesc = ('Migrated from CLIN ' + data.itemNumber + '. Supplier: '
                          + supplierLabel + '. ' + typeLabel).replace(/\s+$/, '');
        $('fl-description').value = ('description' in staged && staged.description !== null && staged.description !== undefined)
            ? staged.description : defaultDesc;

        $('fl-amount-billed').value = ('amount_billed' in staged && staged.amount_billed !== null && staged.amount_billed !== undefined)
            ? staged.amount_billed : (data.quoteValue ? data.quoteValue.toFixed(2) : '0.00');

        if (data.paidAmount) {
            $('fl-auto-payment').value = fmtCurrency(data.paidAmount);
            $('fl-payment-note').textContent = 'A FinanceLinePayment will be auto-created for paid_amount.';
        } else {
            $('fl-auto-payment').value = '— none —';
            $('fl-payment-note').textContent = 'No payment will be auto-created (paid_amount is empty or zero).';
        }

        // Populate parent CLIN picker — same logic as partial shipment picker.
        // Excludes siblings that are being converted away from Default.
        var parentSel = $('fl-parent-clin');
        parentSel.innerHTML = '<option value="">Select a CLIN…</option>';
        var excludeIds = computeExcludeIds(data.id);

        fetch(urls.parentOptions + '?exclude_clin_ids=' + encodeURIComponent(excludeIds.join(',')),
              { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (resp) {
                if (!resp || !resp.success) return;
                resp.options.forEach(function (opt) {
                    var o = document.createElement('option');
                    o.value = opt.id;
                    o.textContent = opt.label;
                    parentSel.appendChild(o);
                });
                // Restore previously staged selection, or default to first
                // available option (lowest item_number) as a convenience default.
                if (staged.parent_clin_id) {
                    parentSel.value = String(staged.parent_clin_id);
                } else if (parentSel.options.length > 1) {
                    parentSel.value = parentSel.options[1].value; // index 0 is placeholder
                }
            })
            .catch(function () { /* silent — server will validate */ });

        var warn = $('fl-income-warning');
        if (warn) {
            if (data.itemValue || data.wawfPayment) {
                warn.style.display = 'block';
                warn.textContent = 'This CLIN has non-zero Item Value or WAWF Payment. ' +
                    'Finance line entries must have no income side. The server will block this conversion.';
            } else {
                warn.style.display = 'none';
            }
        }
    }

    function fillPartialShipmentForm(data) {
        var s = clinFixState[data.id] || { destination_type: 'partial_shipment', staged_data: {} };
        var staged = s.staged_data || {};

        function pickStaged(key, fallback) {
            return (key in staged && staged[key] !== null && staged[key] !== undefined && staged[key] !== '')
                ? staged[key] : fallback;
        }

        $('ps-ship-qty').value = pickStaged('ship_qty', (data.shipQty != null ? data.shipQty : ''));
        $('ps-uom').value = pickStaged('uom', data.uom || '');
        $('ps-quote-value').value = pickStaged('quote_value', data.quoteValue ? data.quoteValue.toFixed(2) : '');
        $('ps-item-value').value = pickStaged('item_value', data.itemValue ? data.itemValue.toFixed(2) : '');
        $('ps-paid-amount').value = pickStaged('paid_amount', data.paidAmount ? data.paidAmount.toFixed(2) : '');
        $('ps-wawf-payment').value = pickStaged('wawf_payment', data.wawfPayment ? data.wawfPayment.toFixed(2) : '');
        $('ps-ship-date').value = pickStaged('ship_date', data.serialized.ship_date || '');
        $('ps-pod-date').value = pickStaged('pod_date', data.serialized.pod_date || '');
        $('ps-comments').value = pickStaged('comments', '');

        // Populate parent CLIN dropdown via API
        var parentSel = $('ps-parent-clin');
        parentSel.innerHTML = '<option value="">Select a parent CLIN…</option>';
        var excludeIds = computeExcludeIds(data.id);

        fetch(urls.parentOptions + '?exclude_clin_ids=' + encodeURIComponent(excludeIds.join(',')),
              { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (resp) {
                if (!resp || !resp.success) return;
                resp.options.forEach(function (opt) {
                    var o = document.createElement('option');
                    o.value = opt.id;
                    o.textContent = opt.label;
                    parentSel.appendChild(o);
                });
                var selectedId = s.parent_clin_id || null;
                if (selectedId) parentSel.value = String(selectedId);
                refreshPartialMismatchWarning(data, parentSel.value);
            })
            .catch(function () { /* silent */ });
    }

    function refreshPartialMismatchWarning(data, parentId) {
        var warn = $('ps-mismatch-warning');
        if (!warn) return;
        if (!parentId) { warn.style.display = 'none'; return; }
        var parentData = getRowData(parentId);
        if (!parentData) { warn.style.display = 'none'; return; }
        var supplierMismatch = (data.supplierId || null) !== (parentData.supplierId || null);
        var nsnMismatch = (data.nsnId || null) !== (parentData.nsnId || null);
        if (supplierMismatch || nsnMismatch) {
            warn.style.display = 'block';
            warn.textContent = 'Parent CLIN supplier/NSN differs from this row. Confirm you want to proceed.';
        } else {
            warn.style.display = 'none';
        }
    }

    function fillDeleteForm(data) {
        var s = clinFixState[data.id] || { destination_type: 'deleted', staged_data: {} };
        $('del-reason').value = (s.staged_data && s.staged_data.reason) || '';
    }

    // ── Switch the pane to match the row's current destination ─────────
    function renderPaneForRow(clinId) {
        if (!clinId) {
            setPaneTitle('Configure');
            showPaneState('A');
            return;
        }
        var data = getRowData(clinId);
        if (!data) return;
        var s = clinFixState[clinId];
        var dest = s ? s.destination_type : 'default';

        setPaneTitle('CLIN ' + (data.itemNumber || clinId));

        if (dest === 'packaging') {
            fillPackagingForm(data);
            showPaneState('C');
        } else if (dest === 'finance_line') {
            fillFinanceLineForm(data);
            showPaneState('D');
        } else if (dest === 'partial_shipment') {
            fillPartialShipmentForm(data);
            showPaneState('E');
        } else if (dest === 'deleted') {
            fillDeleteForm(data);
            showPaneState('F');
        } else {
            fillDefaultPanel(data);
            showPaneState('B');
        }
    }

    function activateRow(clinId) {
        // Persist any in-progress edits on the currently active row before switching
        if (activeClinId && activeClinId !== String(clinId)) syncPaneToState();

        if (!clinId) {
            activeClinId = null;
            setActiveRow(null);
            renderPaneForRow(null);
            return;
        }
        activeClinId = String(clinId);
        setActiveRow(clinId);
        renderPaneForRow(clinId);
    }

    function computeExcludeIds(currentClinId) {
        var ids = [];
        Object.keys(clinFixState).forEach(function (cid) {
            if (isStaged(cid)) ids.push(parseInt(cid, 10));
        });
        if (currentClinId && ids.indexOf(parseInt(currentClinId, 10)) < 0) {
            ids.push(parseInt(currentClinId, 10));
        }
        return ids;
    }

    // ── Draft autosave (debounced per-CLIN) ────────────────────────────
    var debounceTimers = {};
    function saveDraft(clinId) {
        var key = String(clinId);
        if (!clinFixState[key]) {
            // No state → empty record means delete the draft
            clinFixState[key] = { destination_type: 'default', staged_data: {}, parent_clin_id: null, pending_save: true };
        } else {
            clinFixState[key].pending_save = true;
        }
        if (debounceTimers[key]) clearTimeout(debounceTimers[key]);
        debounceTimers[key] = setTimeout(function () { flushDraft(clinId); }, 500);
    }

    function flushDraft(clinId) {
        var key = String(clinId);
        var s = clinFixState[key];
        if (!s) return;
        var body = {
            clin_id: parseInt(clinId, 10),
            destination_type: s.destination_type || 'default',
            staged_data: s.staged_data || {},
            parent_clin_id: s.parent_clin_id || null,
        };
        showSavingIndicator();
        fetch(urls.draftSave, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken(),
            },
            body: JSON.stringify(body),
        })
            .then(function (r) { return r.json().catch(function () { return {}; }); })
            .then(function (resp) {
                if (s) s.pending_save = false;
                if (resp && resp.success) {
                    showSavedIndicator();
                } else {
                    notifyUser('error', (resp && resp.error) || 'Autosave failed.');
                }
            })
            .catch(function () {
                if (s) s.pending_save = false;
                notifyUser('error', 'Network error during autosave.');
            });
    }

    // Read current pane field values into clinFixState[activeClinId].staged_data
    function syncPaneToState() {
        if (!activeClinId) return;
        var s = clinFixState[activeClinId];
        if (!s) return;
        var dest = s.destination_type;
        if (!dest || dest === 'default') return;

        var staged = {};
        var parentClinId = null;

        if (dest === 'packaging') {
            staged.quote_amount = $('pkg-quote').value === '' ? null : $('pkg-quote').value;
            staged.amount_paid = $('pkg-paid').value === '' ? null : $('pkg-paid').value;
            staged.payment_date = $('pkg-payment-date').value || null;
            staged.invoice_number = $('pkg-invoice').value || null;
            staged.notes = $('pkg-notes').value || null;
        } else if (dest === 'finance_line') {
            var lt = $('fl-line-type').value;
            if (lt === 'Other') {
                lt = ($('fl-line-type-other').value || '').trim() || 'Other';
            }
            staged.line_type = lt;
            staged.description = $('fl-description').value || null;
            staged.amount_billed = $('fl-amount-billed').value === '' ? null : $('fl-amount-billed').value;
            // Read the user-selected parent CLIN — stored in staged_data so the
            // server can use it directly instead of auto-picking lowest item_number.
            var flParentVal = $('fl-parent-clin').value;
            parentClinId = flParentVal ? parseInt(flParentVal, 10) : null;
            staged.parent_clin_id = parentClinId;
        } else if (dest === 'partial_shipment') {
            parentClinId = $('ps-parent-clin').value ? parseInt($('ps-parent-clin').value, 10) : null;
            staged.ship_qty = $('ps-ship-qty').value || null;
            staged.uom = $('ps-uom').value || null;
            staged.quote_value = $('ps-quote-value').value || null;
            staged.item_value = $('ps-item-value').value || null;
            staged.paid_amount = $('ps-paid-amount').value || null;
            staged.wawf_payment = $('ps-wawf-payment').value || null;
            staged.ship_date = $('ps-ship-date').value || null;
            staged.pod_date = $('ps-pod-date').value || null;
            staged.comments = ($('ps-comments').value || '').trim();
        } else if (dest === 'deleted') {
            staged.reason = ($('del-reason').value || '').trim();
        }

        s.staged_data = staged;
        s.parent_clin_id = parentClinId;
    }

    // ── Parent-cascade: when a CLIN moves out of Default, any row whose
    //     parent_clin_id === that CLIN must clear its parent and warn. ──
    function invalidateDependents(clinId) {
        Object.keys(clinFixState).forEach(function (cid) {
            var s = clinFixState[cid];
            if (!s) return;
            // Both partial_shipment and finance_line have a parent_clin_id that
            // must be cleared if that parent is being converted away from Default.
            var hasParent = (s.destination_type === 'partial_shipment' || s.destination_type === 'finance_line');
            if (!hasParent) return;
            if (parseInt(s.parent_clin_id, 10) !== parseInt(clinId, 10)) return;
            s.parent_clin_id = null;
            if (s.staged_data) s.staged_data.parent_clin_id = null;
            saveDraft(cid);
            setRowParentCleared(cid, true);
            var depData = getRowData(cid);
            var itemNum = depData ? depData.itemNumber : cid;
            notifyUser('warning', 'CLIN ' + itemNum + ' parent selection cleared — please choose a new parent.');
            if (String(cid) === String(activeClinId)) renderPaneForRow(activeClinId);
        });
    }

    // ── Event handlers ─────────────────────────────────────────────────
    function onDestinationChange(sel) {
        var clinId = sel.dataset.clinId;
        var dest = sel.value;
        var data = getRowData(clinId);
        if (!data) return;

        // Flush any in-progress edits before re-rendering the pane
        if (activeClinId) syncPaneToState();

        // Activate the row no matter what so the pane swaps immediately
        activateRow(clinId);

        if (dest === 'default') {
            // Reverting → delete state and tell server to delete draft
            delete clinFixState[clinId];
            // Send a default-destination request so the server-side draft row
            // (if any) is removed.
            clinFixState[clinId] = {
                destination_type: 'default',
                staged_data: {},
                parent_clin_id: null,
                pending_save: true,
            };
            saveDraft(clinId);
            // After autosave fires, prune the local 'default' record so
            // pending count math stays clean.
            setTimeout(function () {
                if (clinFixState[clinId] && clinFixState[clinId].destination_type === 'default') {
                    delete clinFixState[clinId];
                    updatePendingCount();
                }
            }, 600);
            invalidateDependents(clinId);
            updatePendingCount();
            updateRowVisual(clinId);
            renderPaneForRow(clinId); // shows State B (default original data)
            // Clear parent-cleared visual on the row (user explicitly opted out)
            setRowParentCleared(clinId, false);
            return;
        }

        // Initialize state shell; pane fields will autosave staged_data on input
        var prev = clinFixState[clinId] || {};
        clinFixState[clinId] = {
            destination_type: dest,
            staged_data: prev.staged_data || {},
            parent_clin_id: prev.parent_clin_id || null,
            pending_save: false,
        };

        // Render the pane FIRST so default values populate the inputs
        renderPaneForRow(clinId);
        // Then read those defaults back into staged_data and persist
        syncPaneToState();
        saveDraft(clinId);

        // Other rows that pointed at this row as a parent must be reset
        invalidateDependents(clinId);

        updatePendingCount();
        updateRowVisual(clinId);
        // The cleared-warning ring on this row no longer applies (user
        // is editing it now)
        setRowParentCleared(clinId, false);
    }

    // Top-level change/input listener (delegated)
    document.addEventListener('change', function (e) {
        var destSel = e.target.closest('.clin-fix-destination');
        if (destSel) {
            onDestinationChange(destSel);
            return;
        }
        // Custom Other line-type wrap
        if (e.target && e.target.id === 'fl-line-type') {
            $('fl-line-type-other-wrap').style.display = (e.target.value === 'Other' ? 'block' : 'none');
        }
        // Pane parent-CLIN dropdown — refresh mismatch warning
        if (e.target && e.target.id === 'ps-parent-clin' && activeClinId) {
            syncPaneToState();
            var data = getRowData(activeClinId);
            if (data) refreshPartialMismatchWarning(data, e.target.value);
        }
        // Any pane input change → sync + autosave
        if (e.target && e.target.classList && e.target.classList.contains('pane-input')) {
            syncPaneToState();
            if (activeClinId) saveDraft(activeClinId);
        }
    });

    document.addEventListener('input', function (e) {
        // Live autosave on every keystroke (debounced) for textareas and text inputs
        if (e.target && e.target.classList && e.target.classList.contains('pane-input')) {
            syncPaneToState();
            if (activeClinId) saveDraft(activeClinId);
        }
    });

    // Row click → activate (skip clicks on interactive children)
    document.addEventListener('click', function (e) {
        // Discard drafts button
        if (e.target.closest('#discard-drafts-btn')) {
            if (!confirm('Discard all your draft conversions for this contract?')) return;
            fetch(urls.draftDelete, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken(),
                },
                body: JSON.stringify({}),
            })
                .then(function (r) { return r.json().catch(function () { return {}; }); })
                .then(function (resp) {
                    if (resp && resp.success) {
                        notifyUser('success', 'Drafts discarded (' + (resp.deleted_count || 0) + ').');
                        justSavedSuccessfully = true;
                        window.location.reload();
                    } else {
                        notifyUser('error', (resp && resp.error) || 'Failed to discard drafts.');
                    }
                })
                .catch(function () { notifyUser('error', 'Network error discarding drafts.'); });
            return;
        }
        // Save All button
        if (e.target.closest('#save-all-btn')) {
            saveAllConversions();
            return;
        }
        // Row activation — but ignore clicks on the dropdown, links, buttons
        var rowEl = e.target.closest('.clin-fix-row');
        if (rowEl) {
            if (e.target.closest('.clin-fix-destination, a, button, input, select, textarea')) return;
            activateRow(rowEl.dataset.clinId);
        }
    });

    // ── Save All ───────────────────────────────────────────────────────
    function saveAllConversions() {
        // Make sure the active row's pane values are flushed BEFORE we read state
        syncPaneToState();
        if (activeClinId) flushDraft(activeClinId);

        var conversions = [];
        Object.keys(clinFixState).forEach(function (cid) {
            if (!isStaged(cid)) return;
            var s = clinFixState[cid];
            conversions.push({
                clin_id: parseInt(cid, 10),
                destination_type: s.destination_type,
                staged_data: s.staged_data || {},
                parent_clin_id: s.parent_clin_id || null,
            });
        });
        if (conversions.length === 0) return;

        var btn = $('save-all-btn');
        if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }

        fetch(urls.save, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken(),
            },
            body: JSON.stringify({ conversions: conversions }),
        })
            .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
            .then(function (res) {
                if (res.status === 200 && res.body && res.body.success) {
                    justSavedSuccessfully = true;
                    notifyUser('success',
                        '✓ Saved ' + res.body.conversion_count + ' conversion'
                        + (res.body.conversion_count === 1 ? '' : 's')
                        + ' on Contract ' + contractNumber + '.');
                    setTimeout(function () { window.location.reload(); }, 1200);
                } else {
                    if (res.body && Array.isArray(res.body.errors)) {
                        res.body.errors.forEach(function (e) {
                            if (e.clin_id) {
                                var row = $('clin-fix-row-' + e.clin_id);
                                if (row) row.classList.add('row-error');
                            }
                            notifyUser('error', (e.clin_id ? 'CLIN ' + e.clin_id + ': ' : '') + e.error);
                        });
                    } else {
                        notifyUser('error', (res.body && res.body.error) || 'Save failed.');
                    }
                    if (btn) { btn.disabled = false; btn.textContent = 'Save All Conversions'; }
                }
            })
            .catch(function () {
                notifyUser('error', 'Network error during save.');
                if (btn) { btn.disabled = false; btn.textContent = 'Save All Conversions'; }
            });
    }

    // ── Initial paint ──────────────────────────────────────────────────
    function paintInitial() {
        Object.keys(clinFixState).forEach(function (cid) {
            syncDropdownFromState(cid);
            updateRowVisual(cid);
        });
        updatePendingCount();
        renderPaneForRow(null); // State A — empty

        // Tooltips
        if (window.bootstrap && bootstrap.Tooltip) {
            $$('[data-bs-toggle="tooltip"]').forEach(function (el) {
                try { new bootstrap.Tooltip(el); } catch (e) { /* noop */ }
            });
        }
    }
    paintInitial();

    // ── beforeunload ───────────────────────────────────────────────────
    function hasUnsavedChanges() {
        return Object.keys(clinFixState).some(function (cid) {
            var s = clinFixState[cid];
            return s && s.pending_save === true;
        });
    }
    window.addEventListener('beforeunload', function (e) {
        if (justSavedSuccessfully) return;
        if (hasUnsavedChanges()) {
            e.preventDefault();
            e.returnValue = '';
        }
    });
})();
