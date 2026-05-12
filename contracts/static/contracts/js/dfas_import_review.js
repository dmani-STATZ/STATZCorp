/**
 * DFAS import review: per-row resolution + contract matcher modal.
 * Requires {% csrf_token %}, #dfasResolveRowUrlZero (URL with row_id=0), window.DFAS_CONTRACT_SEARCH_URL.
 */
(function () {
    'use strict';

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

    async function sendResolution(rowId, payload) {
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

    function openContractMatcherModal(rowId, rowEl) {
        const contractNoEl = document.getElementById('dfasMatcherSourceContractNo');
        const callNoEl = document.getElementById('dfasMatcherSourceCallNo');
        const clinEl = document.getElementById('dfasMatcherSourceClin');
        if (contractNoEl) contractNoEl.textContent = rowEl.dataset.rawContractNo || '—';
        if (callNoEl) callNoEl.textContent = rowEl.dataset.rawCallNo || '—';
        if (clinEl) clinEl.textContent = rowEl.dataset.rawClin || '—';

        const modalEl = document.getElementById('dfasContractMatcherModal');
        if (modalEl) modalEl.dataset.targetRowId = String(rowId);

        const input = document.getElementById('dfasContractSearchInput');
        const resultsEl = document.getElementById('dfasContractSearchResults');
        if (input) input.value = '';
        if (resultsEl) {
            resultsEl.innerHTML =
                '<div class="text-center text-body-secondary py-4">Enter at least 3 characters to search.</div>';
        }

        if (modalEl && window.bootstrap && window.bootstrap.Modal) {
            const modal = window.bootstrap.Modal.getOrCreateInstance(modalEl);
            modal.show();
        }
    }

    async function performContractSearch() {
        const searchUrl = window.DFAS_CONTRACT_SEARCH_URL || '/contracts/search/';
        const input = document.getElementById('dfasContractSearchInput');
        const resultsEl = document.getElementById('dfasContractSearchResults');
        if (!input || !resultsEl) return;

        const query = input.value.trim();
        if (query.length < 3) {
            resultsEl.innerHTML =
                '<div class="text-center text-body-secondary py-4">Enter at least 3 characters to search.</div>';
            return;
        }
        resultsEl.innerHTML =
            '<div class="text-center text-body-secondary py-4">Searching…</div>';

        let response;
        try {
            response = await fetch(
                searchUrl + '?q=' + encodeURIComponent(query),
                { credentials: 'same-origin' }
            );
        } catch (e) {
            resultsEl.innerHTML =
                '<div class="text-center text-danger py-4">Search failed.</div>';
            return;
        }
        if (!response.ok) {
            resultsEl.innerHTML =
                '<div class="text-center text-danger py-4">Search failed.</div>';
            return;
        }
        let results;
        try {
            results = await response.json();
        } catch (e) {
            resultsEl.innerHTML =
                '<div class="text-center text-danger py-4">Invalid search response.</div>';
            return;
        }
        if (!Array.isArray(results) || results.length === 0) {
            resultsEl.innerHTML =
                '<div class="text-center text-body-secondary py-4">No matching contracts found.</div>';
            return;
        }

        resultsEl.innerHTML = '';
        results.forEach(function (c) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'list-group-item list-group-item-action';
            const poLine =
                c.po_numbers && c.po_numbers.length
                    ? '<div class="small text-body-secondary">PO: ' +
                      c.po_numbers.map(escapeHtml).join(', ') +
                      '</div>'
                    : '';
            btn.innerHTML =
                '<div class="d-flex justify-content-between align-items-center">' +
                '<div>' +
                '<div class="font-monospace fw-semibold">' +
                escapeHtml(c.contract_number || '') +
                '</div>' +
                poLine +
                '</div>' +
                '<span class="badge bg-secondary">' +
                escapeHtml(c.status || '') +
                '</span>' +
                '</div>';
            btn.addEventListener('click', function () {
                selectContractForMatch(c.id);
            });
            resultsEl.appendChild(btn);
        });
    }

    async function selectContractForMatch(contractId) {
        const modalEl = document.getElementById('dfasContractMatcherModal');
        const rowId = modalEl && modalEl.dataset.targetRowId;
        if (!rowId) return;
        await sendResolution(rowId, {
            action: 'assign_contract',
            contract_id: contractId,
        });
    }

    document.addEventListener('click', async function (event) {
        const target = event.target.closest('[data-action]');
        if (!target) return;

        const action = target.dataset.action;
        const rowEl = target.closest('[data-row-id]');
        if (!rowEl) return;
        const rowId = rowEl.dataset.rowId;
        if (!rowId) return;

        if (action === 'find_contract') {
            openContractMatcherModal(rowId, rowEl);
            return;
        }

        let payload = { action: action };

        if (action === 'assign_clin') {
            const select = rowEl.querySelector('.dfas-clin-select');
            if (!select || !select.value) {
                alert('Please choose a CLIN first.');
                return;
            }
            payload.clin_id = parseInt(select.value, 10);
        }

        await sendResolution(rowId, payload);
    });

    document.addEventListener('DOMContentLoaded', function () {
        const searchBtn = document.getElementById('dfasContractSearchButton');
        const searchInput = document.getElementById('dfasContractSearchInput');
        if (searchBtn) searchBtn.addEventListener('click', performContractSearch);
        if (searchInput) {
            searchInput.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    performContractSearch();
                }
            });
        }
    });
})();
