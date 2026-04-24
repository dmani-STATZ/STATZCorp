// Utility function to show messages
function showMessage(message, type = 'info') {
    const container = document.getElementById('toast-container') || createToastContainer();
    const toast = document.createElement('div');
    toast.className = `toast ${getMessageClass(type)}`;

    const messageBlock = document.createElement('pre');
    messageBlock.className = 'toast-message';
    messageBlock.textContent = message;

    const actions = document.createElement('div');
    actions.className = 'toast-actions';

    const copyButton = document.createElement('button');
    copyButton.type = 'button';
    copyButton.className = 'toast-action';
    copyButton.textContent = 'Copy';
    copyButton.addEventListener('click', () => {
        navigator.clipboard.writeText(message).then(() => {
            copyButton.textContent = 'Copied!';
            setTimeout(() => (copyButton.textContent = 'Copy'), 1500);
        }).catch(() => {
            copyButton.textContent = 'Failed';
            setTimeout(() => (copyButton.textContent = 'Copy'), 1500);
        });
    });

    const closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'toast-close';
    closeButton.setAttribute('aria-label', 'Dismiss message');
    closeButton.innerHTML = '&times;';
    closeButton.addEventListener('click', () => dismissToast(toast));

    actions.appendChild(copyButton);
    actions.appendChild(closeButton);

    toast.appendChild(messageBlock);
    toast.appendChild(actions);
    container.appendChild(toast);

    if (type !== 'error') {
        setTimeout(() => dismissToast(toast), 6000);
    }
}

function createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
    return container;
}

function dismissToast(toast) {
    if (!toast) return;
    toast.classList.add('toast-hide');
    toast.addEventListener('animationend', () => {
        if (toast.parentNode) {
            toast.parentNode.removeChild(toast);
        }
    }, { once: true });
}

function getMessageClass(type) {
    switch (type) {
        case 'success':
            return 'toast-success';
        case 'error':
            return 'toast-error';
        case 'warning':
            return 'toast-warning';
        default:
            return 'toast-info';
    }
}

function showValidationErrors(errors) {
    // Clear any existing validation errors first
    clearValidationErrors();
    
    // Handle contract-level errors
    Object.entries(errors).forEach(([field, error]) => {
        if (field === 'clins') {
            // Handle CLIN-specific errors
            errors[field].forEach(clinError => {
                const clinNumber = clinError.clin_number;
                delete clinError.clin_number;
                
                Object.entries(clinError).forEach(([clinField, clinFieldError]) => {
                    const fieldId = `clin-${clinNumber}-${clinField}`;
                    const element = document.getElementById(fieldId);
                    if (element) {
                        element.classList.add('border-red-500');
                        
                        // Add error message below the field
                        const errorDiv = document.createElement('div');
                        errorDiv.className = 'text-red-500 text-sm mt-1 validation-error';
                        errorDiv.textContent = clinFieldError;
                        element.parentNode.appendChild(errorDiv);
                    }
                });
            });
        } else {
            // Handle contract-level field errors
            const element = document.getElementById(field);
            if (element) {
                element.classList.add('border-red-500');
                
                // Add error message below the field
                const errorDiv = document.createElement('div');
                errorDiv.className = 'text-red-500 text-sm mt-1 validation-error';
                errorDiv.textContent = error;
                element.parentNode.appendChild(errorDiv);
            }
        }
    });
    
    // Show a summary message at the top
    showMessage('Please correct the highlighted fields before finalizing', 'error');
}

function clearValidationErrors() {
    // Remove all validation error styles
    document.querySelectorAll('.border-red-500').forEach(element => {
        element.classList.remove('border-red-500');
    });
    
    // Remove all validation error messages
    document.querySelectorAll('.validation-error').forEach(element => {
        element.remove();
    });
}

// Finalize flow is defined in `process_contract_form.html` (inline) so the correct form action and
// field ids stay in one place. Shared helpers: showMessage, showValidationErrors, clearValidationErrors.

// Update CSS for alerts
const style = document.createElement('style');
style.textContent = `
    #toast-container {
        position: fixed;
        top: 1rem;
        right: 1rem;
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
        z-index: 9999;
        max-width: min(480px, 90vw);
    }

    .toast {
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
        padding: 1rem 1.25rem;
        border-radius: 0.75rem;
        box-shadow: 0 10px 25px rgba(15, 23, 42, 0.18);
        border: 1px solid transparent;
        animation: toast-in 0.2s ease-out;
        backdrop-filter: blur(8px);
    }

    .toast-hide {
        animation: toast-out 0.2s ease-in forwards;
    }

    @keyframes toast-in {
        from {
            opacity: 0;
            transform: translateY(-10px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }

    @keyframes toast-out {
        from {
            opacity: 1;
            transform: translateY(0);
        }
        to {
            opacity: 0;
            transform: translateY(-10px);
        }
    }

    .toast-message {
        margin: 0;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
        font-size: 0.875rem;
        line-height: 1.5;
        white-space: pre-wrap;
        word-break: break-word;
    }

    .toast-actions {
        display: flex;
        justify-content: flex-end;
        gap: 0.5rem;
    }

    .toast-action {
        background: rgba(255, 255, 255, 0.65);
        border: 1px solid rgba(255, 255, 255, 0.7);
        color: inherit;
        padding: 0.35rem 0.75rem;
        border-radius: 0.5rem;
        font-size: 0.75rem;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.15s ease, transform 0.15s ease;
    }

    .toast-action:hover {
        background: rgba(255, 255, 255, 0.85);
        transform: translateY(-1px);
    }

    .toast-close {
        background: transparent;
        border: none;
        color: inherit;
        font-size: 1.25rem;
        line-height: 1;
        cursor: pointer;
        padding: 0.25rem;
        margin-left: 0.25rem;
    }

    .toast-success {
        background: rgba(22, 163, 74, 0.1);
        border-color: rgba(22, 163, 74, 0.25);
        color: #14532d;
    }

    .toast-error {
        background: rgba(220, 38, 38, 0.1);
        border-color: rgba(220, 38, 38, 0.25);
        color: #7f1d1d;
    }

    .toast-warning {
        background: rgba(234, 179, 8, 0.12);
        border-color: rgba(234, 179, 8, 0.28);
        color: #713f12;
    }

    .toast-info {
        background: rgba(59, 130, 246, 0.12);
        border-color: rgba(59, 130, 246, 0.28);
        color: #1e3a8a;
    }

    .error-field {
        border: 2px solid red !important;
        background-color: #fff3f3 !important;
    }
    
    .alert {
        padding: 1rem;
        margin-bottom: 1rem;
        border: 1px solid transparent;
        border-radius: 0.25rem;
        position: relative;
    }
    
    .alert-danger {
        color: #721c24;
        background-color: #f8d7da;
        border-color: #f5c6cb;
    }

    .alert-info {
        color: #0c5460;
        background-color: #d1ecf1;
        border-color: #bee5eb;
    }

    .close {
        position: absolute;
        right: 10px;
        top: 10px;
        padding: 0;
        background: transparent;
        border: 0;
        font-size: 1.5rem;
        font-weight: 700;
        line-height: 1;
        color: inherit;
        opacity: .5;
        cursor: pointer;
    }

    .close:hover {
        opacity: .75;
    }
`;
document.head.appendChild(style);

/**
 * Per-CLIN process splits: add row, calc STATZ, delete, footer totals.
 * Contract-level split table was removed; splits live under each CLIN block in the form.
 */
(function () {
    function getCookie(name) {
        const m = document.cookie.match('(^|;) ?' + name + '=([^;]*)(;|$)');
        return m ? decodeURIComponent(m[2]) : null;
    }

    function csrf() {
        const el = document.querySelector('[name=csrfmiddlewaretoken]');
        return el ? el.value : getCookie('csrftoken');
    }

    function updateClinSplitTotals(table) {
        if (!table) {
            return;
        }
        const clinId = table.getAttribute('data-clin-id');
        let v = 0;
        let p = 0;
        table.querySelectorAll('tbody .clin-split-value-input').forEach((inp) => {
            v += parseFloat(inp.value || 0) || 0;
        });
        table.querySelectorAll('tbody .clin-split-paid-input').forEach((inp) => {
            p += parseFloat(inp.value || 0) || 0;
        });
        const tv = document.querySelector(
            '.clin-splits-total-value[data-clin-id="' + clinId + '"]'
        );
        const tp = document.querySelector(
            '.clin-splits-total-paid[data-clin-id="' + clinId + '"]'
        );
        if (tv) {
            tv.textContent = v.toFixed(2);
        }
        if (tp) {
            tp.textContent = p.toFixed(2);
        }
    }

    function nextNewIndex(clinId) {
        if (!window._clinSplitNewSeq) {
            window._clinSplitNewSeq = {};
        }
        if (window._clinSplitNewSeq[clinId] == null) {
            window._clinSplitNewSeq[clinId] = 0;
        }
        window._clinSplitNewSeq[clinId] += 1;
        return window._clinSplitNewSeq[clinId];
    }

    function addBlankClinSplitRow(clinId) {
        const table = document.getElementById('clin-splits-table-' + clinId);
        if (!table) {
            return;
        }
        const n = nextNewIndex(clinId);
        const tbody = table.querySelector('tbody');
        if (!tbody) {
            return;
        }
        const tr = document.createElement('tr');
        tr.className = 'clin-split-row';
        tr.setAttribute('data-clin-id', clinId);
        tr.setAttribute('data-new', '1');
        tr.innerHTML =
            '<td><input type="text" class="form-control form-control-sm" name="clin-' +
            clinId +
            '-splits-new-' +
            n +
            '-company_name" value=""></td>' +
            '<td><input type="number" step="0.01" class="form-control form-control-sm text-end clin-split-value-input" name="clin-' +
            clinId +
            '-splits-new-' +
            n +
            '-split_value" value="0.00"></td>' +
            '<td><input type="number" step="0.01" class="form-control form-control-sm text-end clin-split-paid-input" name="clin-' +
            clinId +
            '-splits-new-' +
            n +
            '-split_paid" value="0.00"></td>' +
            '<td class="text-center"><button type="button" class="btn btn-sm btn-outline-danger delete-clin-split" data-clin-id="' +
            clinId +
            '">Delete</button></td>';
        tbody.appendChild(tr);
        updateClinSplitTotals(table);
    }

    function findStatzRow(table) {
        if (!table) {
            return null;
        }
        return Array.from(table.querySelectorAll('tbody tr')).find((tr) => {
            const c = tr.querySelector('input[name$="-company_name"]');
            return c && c.value && String(c.value).trim().toLowerCase() === 'statz';
        });
    }

    function appendClinSplitRowFromServer(clinId, data) {
        const table = document.getElementById('clin-splits-table-' + clinId);
        if (!table || !data || !data.split_id) {
            return;
        }
        const sid = data.split_id;
        const v = data.split_value != null ? data.split_value : '0.00';
        const tbody = table.querySelector('tbody');
        const tr = document.createElement('tr');
        tr.className = 'clin-split-row';
        tr.setAttribute('data-split-id', String(sid));
        tr.setAttribute('data-clin-id', String(clinId));
        tr.innerHTML =
            '<td><input type="text" class="form-control form-control-sm" name="clin-' +
            clinId +
            '-splits-' +
            sid +
            '-company_name" value="STATZ"></td>' +
            '<td><input type="number" step="0.01" class="form-control form-control-sm text-end clin-split-value-input" name="clin-' +
            clinId +
            '-splits-' +
            sid +
            '-split_value" value="' +
            v +
            '"></td>' +
            '<td><input type="number" step="0.01" class="form-control form-control-sm text-end clin-split-paid-input" name="clin-' +
            clinId +
            '-splits-' +
            sid +
            '-split_paid" value="0.00"></td>' +
            '<td class="text-center"><button type="button" class="btn btn-sm btn-outline-danger delete-clin-split" data-split-id="' +
            sid +
            '" data-clin-id="' +
            clinId +
            '">Delete</button></td>';
        tbody.appendChild(tr);
        updateClinSplitTotals(table);
    }

    document.addEventListener('click', (e) => {
        const addBtn = e.target.closest('.add-clin-split');
        if (addBtn) {
            e.preventDefault();
            addBlankClinSplitRow(addBtn.getAttribute('data-clin-id'));
            return;
        }

        const calcBtn = e.target.closest('.calc-clin-splits');
        if (calcBtn) {
            e.preventDefault();
            const url = calcBtn.getAttribute('data-calc-url');
            const clinId = calcBtn.getAttribute('data-clin-id');
            if (!url) {
                return;
            }
            const table = document.getElementById('clin-splits-table-' + clinId);
            fetch(url, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrf(),
                    Accept: 'application/json',
                },
            })
                .then((r) => r.json().then((j) => ({ ok: r.ok, j })))
                .then(({ ok, j }) => {
                    if (!ok || !j.success) {
                        throw new Error((j && j.error) || 'Calc failed');
                    }
                    if (!table) {
                        return;
                    }
                    const row = findStatzRow(table);
                    if (row) {
                        const vIn = row.querySelector('.clin-split-value-input');
                        if (vIn) {
                            vIn.value = parseFloat(j.split_value).toFixed(2);
                        }
                    } else {
                        appendClinSplitRowFromServer(clinId, j);
                    }
                    updateClinSplitTotals(table);
                })
                .catch((err) => {
                    if (typeof console !== 'undefined') {
                        console.error(err);
                    }
                    if (typeof showMessage === 'function') {
                        showMessage(String(err), 'error');
                    }
                });
            return;
        }

        const delBtn = e.target.closest('.delete-clin-split');
        if (delBtn) {
            e.preventDefault();
            const splitId = delBtn.getAttribute('data-split-id');
            const clinId = delBtn.getAttribute('data-clin-id');
            const row = delBtn.closest('tr');
            const table = document.getElementById('clin-splits-table-' + clinId);
            if (!splitId) {
                if (row) {
                    row.remove();
                }
                updateClinSplitTotals(table);
                return;
            }
            fetch('/processing/clin/splits/' + splitId + '/delete/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrf(),
                    Accept: 'application/json',
                },
            })
                .then((r) => r.json().then((j) => ({ ok: r.ok, j })))
                .then(({ ok, j }) => {
                    if (!ok || !j.success) {
                        throw new Error((j && j.error) || 'Delete failed');
                    }
                    if (row) {
                        row.remove();
                    }
                    updateClinSplitTotals(table);
                })
                .catch((err) => {
                    if (typeof console !== 'undefined') {
                        console.error(err);
                    }
                    if (typeof showMessage === 'function') {
                        showMessage(String(err), 'error');
                    }
                });
        }
    });

    document.addEventListener('input', (e) => {
        if (
            e.target.classList &&
            (e.target.classList.contains('clin-split-value-input') ||
                e.target.classList.contains('clin-split-paid-input'))
        ) {
            const table = e.target.closest('table');
            updateClinSplitTotals(table);
        }
    });

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('[id^="clin-splits-table-"]').forEach((t) => {
            updateClinSplitTotals(t);
        });
    });
})();
