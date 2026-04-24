/**
 * CLIN-level split CRUD (ClinSplit). Used on clin_detail.html.
 * Expects a root element #clin-splits-root with:
 *   data-list-url, data-add-url, data-update-template, data-delete-template
 *   (update/delete templates use placeholder id 12345, replaced in JS)
 */
function getClinSplitCsrfToken() {
    const i = document.querySelector('[name=csrfmiddlewaretoken]');
    if (i && i.value) return i.value;
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
}

const CLIN_SPLIT_URL_PH = '12345';

const ClinSplits = {
    init() {
        this.root = document.getElementById('clin-splits-root');
        if (!this.root) return;

        this.tbody = this.root.querySelector('#clin-splits-tbody');
        this.footValue = this.root.querySelector('#clin-splits-foot-value');
        this.footPaid = this.root.querySelector('#clin-splits-foot-paid');
        this.addBtn = this.root.querySelector('#clin-splits-add');
        this.addUrl = this.root.getAttribute('data-add-url') || '';
        this.updateTpl = this.root.getAttribute('data-update-template') || '';
        this.deleteTpl = this.root.getAttribute('data-delete-template') || '';

        if (this.addBtn) {
            this.addBtn.addEventListener('click', () => this.startAdd());
        }
        this.root.addEventListener('click', (e) => {
            const save = e.target.closest('.clin-split-save');
            const cancel = e.target.closest('.clin-split-cancel');
            const edit = e.target.closest('.clin-split-edit');
            const del = e.target.closest('.clin-split-delete');
            if (save) { e.preventDefault(); this.saveRow(save); }
            else if (cancel) { e.preventDefault(); this.cancelEdit(cancel); }
            else if (edit) { e.preventDefault(); this.startEdit(edit); }
            else if (del) { e.preventDefault(); this.deleteRow(del); }
        });
        this.recalcFooter();
    },

    _urlUpdate(id) {
        return this.updateTpl.split(CLIN_SPLIT_URL_PH).join(String(id));
    },
    _urlDelete(id) {
        return this.deleteTpl.split(CLIN_SPLIT_URL_PH).join(String(id));
    },

    showMessage(type, message) {
        if (window.notify) window.notify(type === 'error' ? 'error' : 'success', message);
        else console.log(type, message);
    },

    parseNum(s) {
        if (s == null || s === '') return null;
        const n = parseFloat(String(s).replace(/,/g, ''));
        return Number.isFinite(n) ? n : null;
    },

    recalcFooter() {
        if (!this.tbody || !this.footValue || !this.footPaid) return;
        let v = 0;
        let p = 0;
        this.tbody.querySelectorAll('tr.clin-split-data-row').forEach((tr) => {
            const vi = this.parseNum(tr.getAttribute('data-value'));
            const pi = this.parseNum(tr.getAttribute('data-paid'));
            v += vi != null ? vi : 0;
            p += pi != null ? pi : 0;
        });
        this.footValue.textContent = v.toFixed(2);
        this.footPaid.textContent = p.toFixed(2);
    },

    startAdd() {
        if (this.tbody.querySelector('tr.clin-split-new-row')) return;
        const tr = document.createElement('tr');
        tr.className = 'clin-split-new-row';
        tr.innerHTML = `
            <td>
                <label class="form-label small visually-hidden">Company</label>
                <input type="text" class="form-control form-control-sm" name="company_name" required autocomplete="organization" />
            </td>
            <td class="text-end">
                <label class="form-label small visually-hidden">Split value</label>
                <input type="number" step="0.01" class="form-control form-control-sm text-end" name="split_value" />
            </td>
            <td class="text-end">
                <label class="form-label small visually-hidden">Split paid</label>
                <input type="number" step="0.01" class="form-control form-control-sm text-end" name="split_paid" />
            </td>
            <td class="text-center text-nowrap">
                <button type="button" class="btn btn-sm btn-success me-1 clin-split-save-new">Save</button>
                <button type="button" class="btn btn-sm btn-outline-secondary clin-split-cancel-new">Cancel</button>
            </td>
        `;
        tr.querySelector('.clin-split-save-new').addEventListener('click', () => this._submitNew(tr));
        tr.querySelector('.clin-split-cancel-new').addEventListener('click', () => { tr.remove(); });
        this.tbody.appendChild(tr);
    },

    async _submitNew(tr) {
        const nameIn = tr.querySelector('[name=company_name]');
        const vIn = tr.querySelector('[name=split_value]');
        const pIn = tr.querySelector('[name=split_paid]');
        const company = (nameIn && nameIn.value) ? nameIn.value.trim() : '';
        if (!company) {
            this.showMessage('error', 'Company name is required');
            return;
        }
        try {
            const res = await fetch(this.addUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Accept: 'application/json',
                    'X-CSRFToken': getClinSplitCsrfToken()
                },
                body: JSON.stringify({
                    company_name: company,
                    split_value: this.parseNum(vIn && vIn.value) ?? 0,
                    split_paid: this.parseNum(pIn && pIn.value) ?? 0
                })
            });
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error((data && data.error) || 'Add failed');
            tr.remove();
            this.appendDataRow(data);
            this.recalcFooter();
            this.showMessage('success', 'Split saved');
        } catch (e) {
            this.showMessage('error', String(e.message || e));
        }
    },

    appendDataRow(d) {
        if (!d.split_id) return;
        const tr = document.createElement('tr');
        tr.className = 'clin-split-data-row';
        tr.setAttribute('data-id', String(d.split_id));
        const sv = d.split_value != null ? d.split_value : '';
        const sp = d.split_paid != null ? d.split_paid : '';
        tr.setAttribute('data-value', String(sv));
        tr.setAttribute('data-paid', String(sp));
        tr.innerHTML = `
            <td class="clin-split-cell-company">${(d.company_name || '').replace(/</g, '&lt;')}</td>
            <td class="text-end clin-split-cell-value">${this._formatMoneyCell(sv)}</td>
            <td class="text-end clin-split-cell-paid">${this._formatMoneyCell(sp)}</td>
            <td class="text-center text-nowrap">
                <button type="button" class="btn btn-sm btn-outline-primary clin-split-edit">Edit</button>
                <button type="button" class="btn btn-sm btn-outline-danger ms-1 clin-split-delete" data-id="${d.split_id}">Delete</button>
            </td>
        `;
        this.tbody.appendChild(tr);
    },

    _formatMoney(s) {
        if (s === null || s === undefined || s === '') return '—';
        const n = parseFloat(String(s));
        if (!Number.isFinite(n)) return '—';
        return n.toFixed(2);
    },

    _formatMoneyCell(s) {
        const t = this._formatMoney(s);
        return t === '—' ? '—' : ('$' + t);
    },

    startEdit(btn) {
        const tr = btn.closest('tr');
        if (!tr || tr.getAttribute('data-editing') === '1') return;
        tr.setAttribute('data-editing', '1');
        tr.setAttribute('data-prev-html', tr.innerHTML);
        const id = tr.getAttribute('data-id');
        const company = tr.querySelector('.clin-split-cell-company').textContent.trim();
        const valText = (tr.getAttribute('data-value') != null) ? tr.getAttribute('data-value') : '';
        const paidText = (tr.getAttribute('data-paid') != null) ? tr.getAttribute('data-paid') : '';
        tr.innerHTML = `
            <td>
                <input type="text" class="form-control form-control-sm" name="company_name" value="${company.replace(/"/g, '&quot;')}" />
            </td>
            <td class="text-end">
                <input type="number" step="0.01" class="form-control form-control-sm text-end" name="split_value" value="${(valText !== 'null' && valText) ? valText : ''}" />
            </td>
            <td class="text-end">
                <input type="number" step="0.01" class="form-control form-control-sm text-end" name="split_paid" value="${(paidText !== 'null' && paidText) ? paidText : ''}" />
            </td>
            <td class="text-center text-nowrap">
                <button type="button" class="btn btn-sm btn-success me-1 clin-split-save" data-id="${id}">Save</button>
                <button type="button" class="btn btn-sm btn-outline-secondary clin-split-cancel">Cancel</button>
            </td>
        `;
    },

    async saveRow(saveBtn) {
        const tr = saveBtn.closest('tr');
        const id = saveBtn.getAttribute('data-id');
        const v = tr.querySelector('[name=split_value]');
        const p = tr.querySelector('[name=split_paid]');
        const c = tr.querySelector('[name=company_name]');
        try {
            const res = await fetch(this._urlUpdate(id), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Accept: 'application/json',
                    'X-CSRFToken': getClinSplitCsrfToken()
                },
                body: JSON.stringify({
                    company_name: c ? c.value.trim() : '',
                    split_value: this.parseNum(v && v.value),
                    split_paid: this.parseNum(p && p.value)
                })
            });
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error((data && data.error) || 'Update failed');
            tr.removeAttribute('data-editing');
            const newRow = {
                split_id: parseInt(id, 10),
                company_name: c ? c.value.trim() : '',
                split_value: v && v.value !== '' ? v.value : null,
                split_paid: p && p.value !== '' ? p.value : null
            };
            tr.setAttribute('data-value', v && v.value !== '' ? v.value : '');
            tr.setAttribute('data-paid', p && p.value !== '' ? p.value : '');
            tr.className = 'clin-split-data-row';
            tr.setAttribute('data-id', id);
            tr.innerHTML = `
            <td class="clin-split-cell-company">${(newRow.company_name || '').replace(/</g, '&lt;')}</td>
            <td class="text-end clin-split-cell-value">${this._formatMoneyCell(newRow.split_value)}</td>
            <td class="text-end clin-split-cell-paid">${this._formatMoneyCell(newRow.split_paid)}</td>
            <td class="text-center text-nowrap">
                <button type="button" class="btn btn-sm btn-outline-primary clin-split-edit">Edit</button>
                <button type="button" class="btn btn-sm btn-outline-danger ms-1 clin-split-delete" data-id="${id}">Delete</button>
            </td>`;
            this.recalcFooter();
            this.showMessage('success', 'Split updated');
        } catch (e) {
            this.showMessage('error', String(e.message || e));
        }
    },

    cancelEdit(cancelBtn) {
        const tr = cancelBtn.closest('tr');
        if (!tr) return;
        tr.removeAttribute('data-editing');
        tr.innerHTML = tr.getAttribute('data-prev-html') || '';
    },

    async deleteRow(btn) {
        const id = btn.getAttribute('data-id');
        if (!id) return;
        if (!window.confirm('Delete this split?')) return;
        try {
            const res = await fetch(this._urlDelete(id), {
                method: 'POST',
                headers: {
                    Accept: 'application/json',
                    'X-CSRFToken': getClinSplitCsrfToken()
                }
            });
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error((data && data.error) || 'Delete failed');
            const tr = btn.closest('tr');
            if (tr) tr.remove();
            this.recalcFooter();
            this.showMessage('success', 'Split deleted');
        } catch (e) {
            this.showMessage('error', String(e.message || e));
        }
    }
};

window.ClinSplits = ClinSplits;

document.addEventListener('DOMContentLoaded', () => ClinSplits.init());
