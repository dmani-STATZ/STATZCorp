(function () {
    "use strict";

    let snippets = [];

    // Helper to get CSRF token
    function getCsrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || getCookie('csrftoken');
    }

    function getCookie(name) {
        let val = null;
        document.cookie.split(';').forEach(c => {
            const [k, v] = c.trim().split('=');
            if (k === name) val = decodeURIComponent(v);
        });
        return val;
    }

    // Recompute total amount
    function recomputeTotal() {
        let total = 0;
        document.querySelectorAll('.po-line-amount').forEach(input => {
            const val = parseFloat(input.value);
            if (!isNaN(val)) {
                total += val;
            }
        });
        const totalEl = document.getElementById('po-lines-total');
        if (totalEl) {
            totalEl.textContent = total.toFixed(2);
        }
    }

    // Append a new line row to the tbody
    function appendLineRow(line) {
        const tbody = document.getElementById('po-lines-tbody');
        if (!tbody) return;

        const tr = document.createElement('tr');
        tr.dataset.lineId = line.id;
        tr.innerHTML = `
            <td>
                <textarea class="form-control form-control-sm po-line-activity" rows="3">${line.activity || ''}</textarea>
            </td>
            <td>
                <input type="number" step="any" class="form-control form-control-sm po-line-qty" value="${line.qty || ''}">
            </td>
            <td>
                <input type="number" step="any" class="form-control form-control-sm po-line-rate" value="${line.rate || ''}">
            </td>
            <td>
                <input type="number" step="any" class="form-control form-control-sm po-line-amount" value="${line.amount || ''}">
            </td>
            <td class="text-nowrap text-center">
                <button type="button" class="btn btn-outline-secondary btn-sm po-line-up">▲</button>
                <button type="button" class="btn btn-outline-secondary btn-sm po-line-down">▼</button>
                <button type="button" class="btn btn-outline-danger btn-sm po-line-delete">✕</button>
            </td>
        `;
        tbody.appendChild(tr);
    }

    // Delete a line
    function deleteLine(lineId, rowEl) {
        if (!confirm('Are you sure you want to delete this line?')) return;
        fetch(`/contracts/po-line/${lineId}/delete/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCsrfToken()
            }
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                rowEl.remove();
                recomputeTotal();
                if (window.notify) window.notify('success', 'Line item deleted');
            } else {
                if (window.notify) window.notify('error', data.error || 'Failed to delete line');
            }
        })
        .catch(err => {
            console.error(err);
            if (window.notify) window.notify('error', 'Network error deleting line');
        });
    }

    // Move a line and reorder
    function moveLine(rowEl, direction) {
        const tbody = document.getElementById('po-lines-tbody');
        if (direction === 'up') {
            const prev = rowEl.previousElementSibling;
            if (prev) {
                tbody.insertBefore(rowEl, prev);
                saveOrder();
            }
        } else if (direction === 'down') {
            const next = rowEl.nextElementSibling;
            if (next) {
                tbody.insertBefore(next, rowEl);
                saveOrder();
            }
        }
    }

    // Save ordering
    function saveOrder() {
        const poPage = document.getElementById('po-page');
        const poId = poPage.dataset.poId;
        const rows = document.querySelectorAll('#po-lines-tbody tr');
        const orderedIds = [];
        rows.forEach(row => {
            const id = row.dataset.lineId;
            if (id) {
                orderedIds.push(parseInt(id, 10));
            }
        });

        fetch(`/contracts/purchase-order/${poId}/lines/reorder/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({ ordered_ids: orderedIds })
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                if (window.notify) window.notify('success', 'Order updated');
            } else {
                if (window.notify) window.notify('error', data.error || 'Failed to reorder lines');
            }
        })
        .catch(err => {
            console.error(err);
            if (window.notify) window.notify('error', 'Network error reordering lines');
        });
    }

    // Debounced row save
    const saveTimeouts = {};
    function queueRowSave(lineId, rowEl) {
        if (saveTimeouts[lineId]) {
            clearTimeout(saveTimeouts[lineId]);
        }
        saveTimeouts[lineId] = setTimeout(() => {
            saveRow(lineId, rowEl);
        }, 400);
    }

    function saveRow(lineId, rowEl) {
        const activity = rowEl.querySelector('.po-line-activity').value;
        const qty = rowEl.querySelector('.po-line-qty').value;
        const rate = rowEl.querySelector('.po-line-rate').value;
        const amount = rowEl.querySelector('.po-line-amount').value;

        const formData = new FormData();
        formData.append('activity', activity);
        formData.append('qty', qty);
        formData.append('rate', rate);
        formData.append('amount', amount);

        fetch(`/contracts/po-line/${lineId}/update/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCsrfToken()
            },
            body: formData
        })
        .then(res => res.json())
        .then(data => {
            if (!data.success) {
                if (window.notify) window.notify('error', data.error || 'Failed to update line');
            }
        })
        .catch(err => {
            console.error(err);
            if (window.notify) window.notify('error', 'Network error saving line item');
        });
    }

    function handleRowInput(e) {
        const target = e.target;
        if (target.classList.contains('po-line-activity') ||
            target.classList.contains('po-line-qty') ||
            target.classList.contains('po-line-rate') ||
            target.classList.contains('po-line-amount')) {

            const row = target.closest('tr');
            const lineId = row.dataset.lineId;

            // Auto-calculate amount
            if (target.classList.contains('po-line-qty') || target.classList.contains('po-line-rate')) {
                const qtyVal = parseFloat(row.querySelector('.po-line-qty').value);
                const rateVal = parseFloat(row.querySelector('.po-line-rate').value);
                if (!isNaN(qtyVal) && !isNaN(rateVal)) {
                    const amtInput = row.querySelector('.po-line-amount');
                    amtInput.value = (qtyVal * rateVal).toFixed(2);
                }
            }

            recomputeTotal();
            queueRowSave(lineId, row);
        }
    }

    // Load and populate snippets
    function loadSnippets() {
        fetch('/contracts/api/po-snippets/')
            .then(res => res.json())
            .then(data => {
                snippets = data.snippets || [];
                const select = document.getElementById('po-snippet-select');
                if (select) {
                    snippets.forEach(snippet => {
                        const opt = document.createElement('option');
                        opt.value = snippet.id;
                        opt.textContent = snippet.title;
                        select.appendChild(opt);
                    });
                }
            })
            .catch(err => {
                console.error('Error loading snippets:', err);
            });
    }

    // Initialization on DOMContentLoaded / load
    document.addEventListener('DOMContentLoaded', () => {
        recomputeTotal();
        loadSnippets();

        // Wire up snippet select change
        const snippetSelect = document.getElementById('po-snippet-select');
        const snippetPreview = document.getElementById('po-snippet-preview');
        if (snippetSelect && snippetPreview) {
            snippetSelect.addEventListener('change', () => {
                const snippetId = snippetSelect.value;
                const snippet = snippets.find(s => s.id == snippetId);
                if (snippet) {
                    const tempDiv = document.createElement('div');
                    tempDiv.innerHTML = snippet.body;
                    snippetPreview.textContent = tempDiv.textContent || tempDiv.innerText || '';
                } else {
                    snippetPreview.textContent = '';
                }
            });
        }

        // Insert snippet as new line
        const insertSnippetLineBtn = document.getElementById('po-snippet-insert-line-btn');
        if (insertSnippetLineBtn) {
            insertSnippetLineBtn.addEventListener('click', () => {
                const poPage = document.getElementById('po-page');
                const poId = poPage.dataset.poId;
                const text = snippetPreview ? snippetPreview.textContent : '';
                if (!text) {
                    if (window.notify) window.notify('error', 'Please select a snippet first');
                    return;
                }

                const formData = new FormData();
                formData.append('activity', text);

                fetch(`/contracts/purchase-order/${poId}/line/add/`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': getCsrfToken()
                    },
                    body: formData
                })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        appendLineRow(data.line);
                        recomputeTotal();
                        if (window.notify) window.notify('success', 'Snippet inserted as line');
                    } else {
                        if (window.notify) window.notify('error', data.error || 'Failed to insert snippet line');
                    }
                })
                .catch(err => {
                    console.error(err);
                    if (window.notify) window.notify('error', 'Network error inserting snippet');
                });
            });
        }

        // Set snippet as footer
        const setFooterBtn = document.getElementById('po-snippet-set-footer-btn');
        if (setFooterBtn) {
            setFooterBtn.addEventListener('click', () => {
                const footerInput = document.getElementById('po-footer-input');
                if (footerInput && snippetPreview) {
                    footerInput.value = snippetPreview.textContent;
                }
            });
        }

        // Add empty line
        const addLineBtn = document.getElementById('po-add-line-btn');
        if (addLineBtn) {
            addLineBtn.addEventListener('click', () => {
                const poPage = document.getElementById('po-page');
                const poId = poPage.dataset.poId;

                fetch(`/contracts/purchase-order/${poId}/line/add/`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': getCsrfToken()
                    }
                })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        appendLineRow(data.line);
                        recomputeTotal();
                        if (window.notify) window.notify('success', 'Blank line item added');
                    } else {
                        if (window.notify) window.notify('error', data.error || 'Failed to add line item');
                    }
                })
                .catch(err => {
                    console.error(err);
                    if (window.notify) window.notify('error', 'Network error adding line item');
                });
            });
        }

        // Save Header
        const saveHeaderBtn = document.getElementById('po-save-header-btn');
        if (saveHeaderBtn) {
            saveHeaderBtn.addEventListener('click', () => {
                const poPage = document.getElementById('po-page');
                const poId = poPage.dataset.poId;
                const poNumber = document.getElementById('po-number-input').value;
                const poDate = document.getElementById('po-date-input').value;
                const footer = document.getElementById('po-footer-input').value;

                const formData = new FormData();
                formData.append('po_number', poNumber);
                formData.append('po_date', poDate);
                formData.append('footer', footer);

                const supplierSelect = document.getElementById('po-supplier-select');
                if (supplierSelect) {
                    formData.append('supplier_id', supplierSelect.value);
                }

                fetch(`/contracts/purchase-order/${poId}/update/`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': getCsrfToken()
                    },
                    body: formData
                })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        if (window.notify) window.notify('success', 'Header details saved successfully');
                    } else {
                        if (window.notify) window.notify('error', data.error || 'Failed to save header details');
                    }
                })
                .catch(err => {
                    console.error(err);
                    if (window.notify) window.notify('error', 'Network error saving header details');
                });
            });
        }

        // Delegated row listeners
        const tbody = document.getElementById('po-lines-tbody');
        if (tbody) {
            tbody.addEventListener('click', e => {
                const target = e.target;
                const row = target.closest('tr');
                if (!row) return;
                const lineId = row.dataset.lineId;

                if (target.classList.contains('po-line-up')) {
                    e.preventDefault();
                    moveLine(row, 'up');
                } else if (target.classList.contains('po-line-down')) {
                    e.preventDefault();
                    moveLine(row, 'down');
                } else if (target.classList.contains('po-line-delete')) {
                    e.preventDefault();
                    deleteLine(lineId, row);
                }
            });

            tbody.addEventListener('change', handleRowInput);
            tbody.addEventListener('focusout', handleRowInput);
        }
    });
})();
