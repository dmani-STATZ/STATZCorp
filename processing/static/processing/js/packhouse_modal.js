(function () {
    'use strict';

    const MIN_LEN = 3;
    let currentProcessContractId = null;
    let selectedSupplierId = null;
    let selectedRowEl = null;

    function getModalEl() {
        return document.getElementById('packhouse_modal');
    }

    function getCompactRoot() {
        return document.getElementById('packhouse_compact_root');
    }

    function closePackhouseModal() {
        const el = getModalEl();
        if (el) {
            el.classList.add('hidden');
        }
    }

    window.closePackhouseModal = closePackhouseModal;

    function getCsrfToken() {
        const el = document.querySelector('[name=csrfmiddlewaretoken]');
        return el ? el.value : '';
    }

    function getMatchUrl() {
        const m = getModalEl();
        return m ? m.getAttribute('data-packhouse-match-url') : '';
    }

    function getSearchUrl() {
        const m = getModalEl();
        return m ? m.getAttribute('data-supplier-search-url') : '';
    }

    function getPackhouseInputs() {
        return {
            quote: document.getElementById('cont_packhouse_quote_amount'),
            notes: document.getElementById('cont_packhouse_notes'),
            hidden: document.getElementById('id_packhouse'),
        };
    }

    function applyPlanGrossFromResponse(data) {
        if (!data || data.plan_gross == null || data.plan_gross === '') {
            return;
        }
        const planGrossInput = document.querySelector('input[name="cont_plan_gross"]');
        if (planGrossInput) {
            planGrossInput.value = data.plan_gross;
        }
    }

    function escapeHtml(t) {
        const d = document.createElement('div');
        d.textContent = t == null ? '' : String(t);
        return d.innerHTML;
    }

    function escapeAttr(t) {
        return String(t == null ? '' : t)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/</g, '&lt;');
    }

    function setCompactRootDataset(pcId, name, cage, isPackhouse) {
        const root = getCompactRoot();
        if (!root) return;
        root.dataset.processContractId = String(pcId);
        root.dataset.phName = name || '';
        root.dataset.phCage = cage || '';
        root.dataset.phIs = isPackhouse ? '1' : '0';
    }

    function renderPackhouseCompactUnassigned(pcId) {
        const inner = document.getElementById('packhouse_compact_inner');
        if (!inner) return;
        setCompactRootDataset(pcId, '', '', false);
        inner.innerHTML =
            '<div class="d-flex align-items-center justify-content-between gap-2 py-1">' +
            '<div class="d-flex align-items-center gap-2 min-w-0">' +
            '<span class="flex-shrink-0" aria-hidden="true">📦</span>' +
            '<span class="text-muted small text-truncate">No packhouse assigned</span>' +
            '</div>' +
            '<button type="button" class="btn btn-sm btn-outline-primary flex-shrink-0" data-packhouse-action="assign">Assign Packhouse</button>' +
            '</div>';
    }

    function renderPackhouseCompactAssigned(pcId, name, cage, isPackhouse, quoteVal, notesVal) {
        const inner = document.getElementById('packhouse_compact_inner');
        if (!inner) return;
        setCompactRootDataset(pcId, name, cage, isPackhouse);
        const badge = isPackhouse
            ? '<span class="badge bg-success ms-1 flex-shrink-0">Packhouse</span>'
            : '';
        const q = escapeAttr(quoteVal != null ? String(quoteVal) : '');
        const n = escapeAttr(notesVal != null ? String(notesVal) : '');
        inner.innerHTML =
            '<div class="d-flex align-items-center justify-content-between gap-2 py-1 flex-wrap">' +
            '<div class="d-flex align-items-center gap-2 min-w-0 flex-grow-1">' +
            '<span class="flex-shrink-0" aria-hidden="true">📦</span>' +
            '<span class="fw-semibold text-truncate">' +
            escapeHtml(name) +
            '</span>' +
            (cage
                ? '<span class="text-muted small flex-shrink-0">(' + escapeHtml(cage) + ')</span>'
                : '') +
            badge +
            '</div>' +
            '<div class="d-flex align-items-center gap-1 flex-shrink-0">' +
            '<button type="button" class="btn btn-sm btn-outline-secondary" data-packhouse-action="edit">Edit</button>' +
            '<button type="button" class="btn btn-sm btn-outline-danger" data-packhouse-action="clear">Clear</button>' +
            '</div>' +
            '</div>' +
            '<div class="d-flex flex-wrap align-items-center gap-2 py-1">' +
            '<label class="small text-muted mb-0 flex-shrink-0" for="cont_packhouse_quote_amount">Quote:</label>' +
            '<input type="number" step="0.01" class="form-control form-control-sm packhouse-quote-input" style="width:7rem;max-width:40%" id="cont_packhouse_quote_amount" name="cont_packhouse_quote_amount" value="' +
            q +
            '">' +
            '<label class="small text-muted mb-0 flex-shrink-0" for="cont_packhouse_notes">Notes:</label>' +
            '<textarea class="form-control form-control-sm packhouse-notes-compact flex-grow-1" rows="1" id="cont_packhouse_notes" name="cont_packhouse_notes">' +
            escapeHtml(notesVal) +
            '</textarea>' +
            '</div>';
    }

    function getProcessContractIdFromPage() {
        const root = getCompactRoot();
        if (root && root.dataset.processContractId) {
            return root.dataset.processContractId;
        }
        return currentProcessContractId != null ? String(currentProcessContractId) : '';
    }

    async function postUpdateProcessContractField(fieldName, fieldValue) {
        const pcId = getProcessContractIdFromPage();
        if (!pcId) return null;
        const fd = new FormData();
        fd.append('field_name', fieldName);
        fd.append('field_value', fieldValue != null ? String(fieldValue) : '');
        const res = await fetch('/processing/api/update-field/' + pcId + '/', {
            method: 'POST',
            body: fd,
            headers: { 'X-CSRFToken': getCsrfToken() },
        });
        return res.json();
    }

    async function runPackhouseClear() {
        if (
            !window.confirm(
                'Remove packhouse assignment? This will also clear the quote amount and notes.'
            )
        ) {
            return;
        }
        const data = await postMatchJson({ action: 'clear' });
        if (data.success && data.cleared) {
            const pcId = getProcessContractIdFromPage();
            renderPackhouseCompactUnassigned(pcId);
            updateHiddenPackhouseId('');
            applyPlanGrossFromResponse(data);
            if (typeof saveContract === 'function') saveContract();
            closePackhouseModal();
        } else if (data.error) {
            alert(data.error);
        } else if (data.message) {
            alert(data.message);
        }
    }

    function updateHiddenPackhouseId(supplierId) {
        const h = getPackhouseInputs().hidden;
        if (h) {
            h.value = supplierId != null && supplierId !== '' ? String(supplierId) : '';
        }
    }

    function setSaveEnabled() {
        const btn = document.getElementById('packhouse_save_btn');
        if (!btn) return;
        const addWrap = document.getElementById('packhouse_add_form_wrap');
        const addVisible = addWrap && !addWrap.classList.contains('d-none');
        let addValid = false;
        if (addVisible) {
            const n = (document.getElementById('packhouse_new_name') || {}).value;
            const c = (document.getElementById('packhouse_new_cage') || {}).value;
            addValid = !!(n && String(n).trim() && c && String(c).trim());
        }
        btn.disabled = !(selectedSupplierId || addValid);
    }

    function clearSelectionHighlight() {
        if (selectedRowEl) {
            selectedRowEl.classList.remove('active');
            selectedRowEl = null;
        }
        selectedSupplierId = null;
        setSaveEnabled();
    }

    function renderSearchResults(options) {
        const container = document.getElementById('packhouse_search_results');
        if (!container) return;
        if (!options || !options.length) {
            container.innerHTML =
                '<div class="text-muted small p-2">No suppliers found. Try a different search.</div>';
            return;
        }

        function rowHtml(o) {
            const label = o.label || o.name || '';
            const badge = o.is_packhouse ? '<span class="ms-1" title="Packhouse">📦</span>' : '';
            const cage = o.cage_code
                ? '<span class="text-muted small ms-2">' + escapeHtml(o.cage_code) + '</span>'
                : '';
            return (
                '<button type="button" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center packhouse-result-row" ' +
                'data-supplier-id="' +
                o.value +
                '" data-name="' +
                escapeAttr(label) +
                '" data-cage="' +
                escapeAttr(o.cage_code || '') +
                '" data-is-packhouse="' +
                (o.is_packhouse ? '1' : '0') +
                '">' +
                '<span><span class="fw-medium">' +
                escapeHtml(label) +
                '</span>' +
                cage +
                badge +
                '</span></button>'
            );
        }

        const pack = options.filter(function (o) {
            return o.is_packhouse;
        });
        const other = options.filter(function (o) {
            return !o.is_packhouse;
        });
        let html = '';
        if (pack.length) {
            html += '<h6 class="dropdown-header mb-0">Packhouses</h6>';
            html += pack.map(rowHtml).join('');
        }
        if (other.length) {
            html += '<h6 class="dropdown-header mb-0 mt-1">Other Suppliers</h6>';
            html += other.map(rowHtml).join('');
        }
        container.innerHTML = html;
        container.querySelectorAll('.packhouse-result-row').forEach(function (row) {
            row.addEventListener('click', function () {
                clearSelectionHighlight();
                selectedSupplierId = row.getAttribute('data-supplier-id');
                selectedRowEl = row;
                row.classList.add('active');
                const addWrap = document.getElementById('packhouse_add_form_wrap');
                if (addWrap) addWrap.classList.add('d-none');
                setSaveEnabled();
            });
        });
    }

    async function runSearch() {
        const input = document.getElementById('packhouse_search');
        const container = document.getElementById('packhouse_search_results');
        if (!input || !container) return;
        const q = input.value.trim();
        if (q.length < MIN_LEN) {
            container.innerHTML =
                '<div class="text-muted small p-2">Enter at least ' + MIN_LEN + ' characters to search.</div>';
            return;
        }
        container.innerHTML =
            '<div class="d-flex align-items-center gap-2 p-3"><div class="spinner-border spinner-border-sm" role="status"></div><span class="small text-muted">Searching…</span></div>';
        const base = getSearchUrl();
        const url =
            base +
            '?search=' +
            encodeURIComponent(q) +
            '&page=1&page_size=20&prefer_packhouse=1';
        try {
            const res = await fetch(url, {
                headers: { 'X-CSRFToken': getCsrfToken() },
            });
            const data = await res.json();
            if (data.success && data.options) {
                const normalized = data.options.map(function (o) {
                    return {
                        value: o.value,
                        label: o.label,
                        cage_code: o.cage_code != null ? o.cage_code : '',
                        is_packhouse: !!o.is_packhouse,
                    };
                });
                renderSearchResults(normalized);
            } else {
                container.innerHTML = '<div class="text-danger small p-2">Search failed.</div>';
            }
        } catch (e) {
            container.innerHTML = '<div class="text-danger small p-2">Search failed.</div>';
        }
    }

    async function postMatchJson(body) {
        const url = getMatchUrl();
        const res = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify(body),
        });
        return res.json();
    }

    function wireCompactSectionDelegation() {
        if (window.__phPackhouseDelegationBound === '1') {
            return;
        }
        window.__phPackhouseDelegationBound = '1';
        document.addEventListener(
            'click',
            function (e) {
                const btn = e.target.closest('[data-packhouse-action]');
                if (!btn) return;
                const root = getCompactRoot();
                if (!root || !root.contains(btn)) return;
                const act = btn.getAttribute('data-packhouse-action');
                const pcId = parseInt(root.dataset.processContractId || '0', 10) || 0;
                if (act === 'assign' || act === 'edit') {
                    const name = root.dataset.phName || '';
                    const cage = root.dataset.phCage || '';
                    const text = cage ? name + ' (' + cage + ')' : name;
                    if (typeof window.openPackhouseModal === 'function') {
                        window.openPackhouseModal(pcId, text);
                    }
                } else if (act === 'clear') {
                    runPackhouseClear();
                }
            },
            true
        );
        document.addEventListener('focusout', function (e) {
            const root = getCompactRoot();
            if (!root || !root.contains(e.target)) return;
            const t = e.target;
            if (!t || !t.id) return;
            if (t.id === 'cont_packhouse_quote_amount') {
                postUpdateProcessContractField('packhouse_quote_amount', t.value).then(function (data) {
                    if (data && data.status === 'success' && data.plan_gross != null) {
                        applyPlanGrossFromResponse(data);
                    }
                });
            } else if (t.id === 'cont_packhouse_notes') {
                postUpdateProcessContractField('packhouse_notes', t.value);
            }
        });
        const root = getCompactRoot();
        if (root) {
            root.dataset.phDelegationBound = '1';
        }
    }

    window.openPackhouseModal = function (processContractId, currentPackhouseText) {
        currentProcessContractId = processContractId;
        const modalEl = getModalEl();
        if (!modalEl) return;
        const orig = document.getElementById('packhouse_original_display');
        if (orig) {
            orig.textContent = currentPackhouseText
                ? 'Packhouse: ' + currentPackhouseText
                : 'Packhouse: (none)';
        }
        const search = document.getElementById('packhouse_search');
        if (search) search.value = '';
        const addWrap = document.getElementById('packhouse_add_form_wrap');
        if (addWrap) addWrap.classList.add('d-none');
        const nameEl = document.getElementById('packhouse_new_name');
        const cageEl = document.getElementById('packhouse_new_cage');
        const chk = document.getElementById('packhouse_new_is_packhouse');
        if (nameEl) nameEl.value = '';
        if (cageEl) cageEl.value = '';
        if (chk) chk.checked = true;
        clearSelectionHighlight();
        const results = document.getElementById('packhouse_search_results');
        if (results) results.innerHTML = '';
        const saveBtn = document.getElementById('packhouse_save_btn');
        if (saveBtn) saveBtn.disabled = true;
        modalEl.classList.remove('hidden');
        if (search) {
            search.focus();
        }
    };

    wireCompactSectionDelegation();

    function initPackhouseModal() {
        const searchInput = document.getElementById('packhouse_search');
        if (searchInput) {
            let t = null;
            searchInput.addEventListener('input', function () {
                clearTimeout(t);
                t = setTimeout(runSearch, 300);
            });
        }
        const toggleAdd = document.getElementById('packhouse_toggle_add');
        if (toggleAdd) {
            toggleAdd.addEventListener('click', function () {
                const wrap = document.getElementById('packhouse_add_form_wrap');
                if (!wrap) return;
                wrap.classList.toggle('d-none');
                clearSelectionHighlight();
                setSaveEnabled();
            });
        }
        const nameNew = document.getElementById('packhouse_new_name');
        const cageNew = document.getElementById('packhouse_new_cage');
        const chkNew = document.getElementById('packhouse_new_is_packhouse');
        if (nameNew) nameNew.addEventListener('input', setSaveEnabled);
        if (cageNew) cageNew.addEventListener('input', setSaveEnabled);
        if (chkNew) chkNew.addEventListener('change', setSaveEnabled);
        const saveBtn = document.getElementById('packhouse_save_btn');
        if (saveBtn) {
            saveBtn.addEventListener('click', async function () {
                const addWrap = document.getElementById('packhouse_add_form_wrap');
                const useCreate = addWrap && !addWrap.classList.contains('d-none');
                const prev = getPackhouseInputs();
                const carryQuote = prev.quote ? prev.quote.value : '';
                const carryNotes = prev.notes ? prev.notes.value : '';
                let data;
                if (useCreate) {
                    const name = (document.getElementById('packhouse_new_name') || {}).value.trim();
                    const cage = (document.getElementById('packhouse_new_cage') || {}).value.trim();
                    const isPh = (document.getElementById('packhouse_new_is_packhouse') || {}).checked;
                    const body = { action: 'create', name: name, cage_code: cage };
                    if (isPh) {
                        body.is_packhouse = true;
                    }
                    data = await postMatchJson(body);
                } else if (selectedSupplierId) {
                    data = await postMatchJson({ action: 'match', supplier_id: selectedSupplierId });
                } else {
                    return;
                }
                if (data.success) {
                    const pcId = getProcessContractIdFromPage();
                    renderPackhouseCompactAssigned(
                        pcId,
                        data.packhouse_name,
                        data.packhouse_cage,
                        data.is_packhouse,
                        carryQuote,
                        carryNotes
                    );
                    updateHiddenPackhouseId(data.packhouse_id);
                    applyPlanGrossFromResponse(data);
                    if (typeof saveContract === 'function') saveContract();
                    closePackhouseModal();
                } else if (data.error) {
                    alert(data.error);
                } else if (data.message) {
                    alert(data.message);
                }
            });
        }
        const clearBtn = document.getElementById('packhouse_clear_btn');
        if (clearBtn) {
            clearBtn.addEventListener('click', async function () {
                await runPackhouseClear();
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initPackhouseModal);
    } else {
        // DOM already parsed — run init immediately (script at end of long body).
        initPackhouseModal();
    }
})();
