/**
 * Log Split Paid modal — Finance Audit page.
 *
 * Opens when the "Split Paid" header button is clicked.
 * One input per company. On save, POSTs total_paid per company
 * to log_split_paid endpoint which distributes proportionally
 * across CLINs. Updates DOM on success without page reload.
 * Discrepant amounts require a second Save click per company block.
 */
(function () {
    'use strict';

    function csrfToken() {
        const el = document.querySelector('[name=csrfmiddlewaretoken]');
        if (el) return el.value;
        const m = document.cookie.match(/csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }

    function fmt(val) {
        if (val === null || val === undefined) return '—';
        const n = parseFloat(val);
        return Number.isFinite(n) ? '$' + n.toFixed(2) : '—';
    }

    function resetBlockConfirm(block) {
        block._confirmed = false;
        block.classList.remove('log-split-confirmed', 'border-warning', 'border-start', 'border-3');
        const discMsg = block.querySelector('.log-split-discrepancy-msg');
        if (discMsg) {
            discMsg.classList.add('d-none');
            discMsg.textContent = '';
        }
    }

    function showClientDiscrepancy(block, totalPaid, totalValue) {
        const discMsg = block.querySelector('.log-split-discrepancy-msg');
        if (!discMsg) return;
        const diff = totalPaid - totalValue;
        const sign = diff > 0 ? '+' : '';
        discMsg.textContent = `⚠ Paid differs from split value by ${sign}$${Math.abs(diff).toFixed(2)}. Click Save again to confirm.`;
        discMsg.classList.remove('d-none');
    }

    function enterConfirmState(block, totalPaid, totalValue) {
        block._confirmed = true;
        block.classList.add('log-split-confirmed', 'border-warning', 'border-start', 'border-3');
        showClientDiscrepancy(block, totalPaid, totalValue);
    }

    function attachInputListeners() {
        document.querySelectorAll('.log-split-company-block').forEach(function (block) {
            block._confirmed = false;
            const input = block.querySelector('.log-split-paid-input');
            if (!input) return;
            input.addEventListener('input', function () {
                resetBlockConfirm(block);
            });
        });
    }

    function buildModalBody() {
        const data = window.splitPaidData || {};
        const companies = Object.keys(data);
        if (!companies.length) {
            return '<p class="text-body-secondary">No split data found for this contract.</p>';
        }

        let html = '<p class="text-body-secondary small mb-3">'
            + 'Enter the total amount paid per company. The system will distribute '
            + 'proportionally across CLINs based on each CLIN\'s split value.'
            + '</p>';

        html += '<div class="d-flex flex-column gap-3">';
        companies.forEach(function (company) {
            const cd = data[company];
            const currentPaid = cd.total_paid !== null ? cd.total_paid : '';
            html += `
            <div class="border rounded p-3 log-split-company-block"
                 data-company="${company.replace(/"/g, '&quot;')}">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <span class="fw-semibold">${company.replace(/</g, '&lt;')}</span>
                    <span class="text-body-secondary small">
                        Split Value: <strong>${fmt(cd.total_value)}</strong>
                    </span>
                </div>
                <div class="mb-1">
                    <label class="form-label form-label-sm mb-1">
                        Total Paid
                    </label>
                    <input type="number" step="0.01" min="0"
                           class="form-control form-control-sm log-split-paid-input"
                           data-company="${company.replace(/"/g, '&quot;')}"
                           placeholder="${currentPaid !== '' ? currentPaid : '0.00'}"
                           value="${currentPaid}" />
                </div>
                <div class="log-split-discrepancy-msg text-warning small mt-1 d-none"></div>
                <div class="log-split-clin-breakdown mt-2 d-none">
                    <table class="table table-sm mb-0">
                        <thead>
                            <tr>
                                <th class="ps-0">CLIN</th>
                                <th class="text-end">Split Value</th>
                                <th class="text-end">Split Paid</th>
                            </tr>
                        </thead>
                        <tbody class="log-split-clin-tbody"></tbody>
                    </table>
                </div>
            </div>`;
        });
        html += '</div>';
        return html;
    }

    function openModal() {
        const body = document.getElementById('logSplitPaidModalBody');
        if (body) body.innerHTML = buildModalBody();
        attachInputListeners();
        const modal = bootstrap.Modal.getOrCreateInstance(
            document.getElementById('logSplitPaidModal')
        );
        modal.show();
    }

    function closeModal() {
        const el = document.getElementById('logSplitPaidModal');
        if (!el) return;
        const modal = bootstrap.Modal.getInstance(el);
        if (modal) modal.hide();
    }

    function applySaveSuccess(block, company, data) {
        const tbody = block.querySelector('.log-split-clin-tbody');
        const breakdownDiv = block.querySelector('.log-split-clin-breakdown');
        if (tbody && data.splits) {
            tbody.innerHTML = data.splits.map(function (s) {
                return `<tr>
                    <td class="ps-0">${s.item_number}</td>
                    <td class="text-end">${fmt(s.split_value)}</td>
                    <td class="text-end">${fmt(s.split_paid)}</td>
                </tr>`;
            }).join('');
            if (breakdownDiv) breakdownDiv.classList.remove('d-none');
        }

        const discMsg = block.querySelector('.log-split-discrepancy-msg');
        if (discMsg) {
            if (data.discrepancy) {
                const diff = parseFloat(data.discrepancy_amount);
                const sign = diff > 0 ? '+' : '';
                discMsg.textContent = `⚠ Paid differs from split value by ${sign}$${Math.abs(diff).toFixed(2)}`;
                discMsg.classList.remove('d-none');
            } else {
                discMsg.classList.add('d-none');
                discMsg.textContent = '';
            }
        }

        block._confirmed = false;
        block.classList.remove('log-split-confirmed', 'border-warning', 'border-start', 'border-3');

        if (window.splitPaidData && window.splitPaidData[company]) {
            window.splitPaidData[company].total_paid = parseFloat(data.company_total_paid);
        }

        const companyRow = document.querySelector(
            `.finance-split-company-row[data-company="${CSS.escape(company)}"]`
        );
        if (companyRow) {
            const cells = companyRow.querySelectorAll('td');
            if (cells[2]) {
                cells[2].textContent = fmt(data.company_total_paid);
            }
        }

        if (data.splits) {
            data.splits.forEach(function (s) {
                const clinRow = document.querySelector(
                    `.finance-split-clin-table tr[data-split-id="${s.split_id}"]`
                );
                if (clinRow) {
                    const clinCells = clinRow.querySelectorAll('td');
                    if (clinCells[2]) {
                        clinCells[2].textContent = fmt(s.split_paid);
                    }
                }
            });
        }

        updateTotalPaidFooter();
    }

    async function postCompanySplit(company, totalPaid) {
        const res = await fetch(window.logSplitPaidUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-CSRFToken': csrfToken(),
            },
            body: JSON.stringify({
                company_name: company,
                total_paid: totalPaid.toFixed(2),
            }),
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
            throw new Error(data.error || 'Save failed');
        }
        return data;
    }

    async function saveAll() {
        const saveBtn = document.getElementById('logSplitPaidSaveBtn');
        if (!saveBtn) return;

        const blocks = document.querySelectorAll('.log-split-company-block');
        if (!blocks.length) return;

        saveBtn.disabled = true;
        saveBtn.textContent = 'Saving…';

        let anyError = false;
        let needsConfirm = false;
        let anySaved = false;

        for (const block of blocks) {
            const company = block.getAttribute('data-company');
            const input = block.querySelector('.log-split-paid-input');
            const rawVal = input ? input.value.trim() : '';

            if (rawVal === '') continue;

            const totalPaid = parseFloat(rawVal);
            if (!Number.isFinite(totalPaid)) {
                if (window.notify) window.notify('error', `Invalid amount for ${company}`);
                anyError = true;
                continue;
            }

            const totalValue = (window.splitPaidData[company] || {}).total_value || 0;
            const hasDiscrepancy = Math.abs(totalPaid - totalValue) > 0.01;

            if (hasDiscrepancy && !block._confirmed) {
                enterConfirmState(block, totalPaid, totalValue);
                needsConfirm = true;
                continue;
            }

            try {
                const data = await postCompanySplit(company, totalPaid);
                applySaveSuccess(block, company, data);
                anySaved = true;
            } catch (e) {
                if (window.notify) window.notify('error', `${company}: ${e.message || 'Save failed'}`);
                anyError = true;
            }
        }

        saveBtn.disabled = false;
        saveBtn.textContent = 'Save';

        if (!anyError && !needsConfirm) {
            closeModal();
            if (anySaved && window.notify) {
                window.notify('success', 'Split paid values saved.');
            }
        }
    }

    function updateTotalPaidFooter() {
        const tbody = document.querySelector(
            '.finance-audit-split-card table tbody'
        );
        const tfoot = document.querySelector(
            '.finance-audit-split-card table tfoot'
        );
        if (!tbody || !tfoot) return;

        let total = 0;
        tbody.querySelectorAll('.finance-split-company-row').forEach(function (row) {
            const cell = row.querySelectorAll('td')[2];
            if (cell) {
                const val = parseFloat((cell.textContent || '').replace(/[$,]/g, ''));
                if (Number.isFinite(val)) total += val;
            }
        });

        const footCells = tfoot.querySelectorAll('td');
        if (footCells[1]) {
            footCells[1].textContent = '$' + total.toFixed(2);
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        const openBtn = document.getElementById('log-split-paid-btn');
        if (openBtn) {
            openBtn.addEventListener('click', openModal);
        }

        const saveBtn = document.getElementById('logSplitPaidSaveBtn');
        if (saveBtn) {
            saveBtn.addEventListener('click', saveAll);
        }
    });
})();
