
document.addEventListener('DOMContentLoaded', function() {
    // ============================================
    // LOADING STATES & TOAST NOTIFICATION SYSTEM
    // ============================================
    
    function showToast(message, type = 'success', duration = 3000) {
        if (window.notify) {
            window.notify(type, message, duration);
        }
    }
    
    // Button loading state helpers
    function setButtonLoading(btn, loading) {
        if (!btn) return;
        const textEl = btn.querySelector('.btn-text');
        const spinnerEl = btn.querySelector('.btn-spinner');
        if (textEl && spinnerEl) {
            if (loading) {
                textEl.classList.add('hidden');
                spinnerEl.classList.remove('hidden');
                btn.disabled = true;
            } else {
                textEl.classList.remove('hidden');
                spinnerEl.classList.add('hidden');
                btn.disabled = false;
            }
        } else {
            btn.disabled = loading;
        }
    }
    
    // Search loading state
    const searchWrapper = document.getElementById('search-wrapper');
    function setSearchLoading(loading) {
        if (searchWrapper) {
            searchWrapper.classList.toggle('loading', loading);
        }
    }
    
    // Detail panel loading overlay
    const detailOverlay = document.getElementById('detail-loading-overlay');
    function setDetailLoading(loading) {
        if (detailOverlay) {
            detailOverlay.classList.toggle('active', loading);
        }
    }
    
    // Select loading state
    function setSelectLoading(select, loading) {
        if (!select) return;
        select.classList.toggle('loading', loading);
        select.disabled = loading;
    }
    
    // Tab switching (persist tab in URL so deep links keep state)
    const tabButtons = document.querySelectorAll('[data-tab]');
    const tabPanels = document.querySelectorAll('[data-panel]');
    let currentTab = new URL(window.location).searchParams.get('tab') || 'info';
    tabButtons.forEach(btn => btn.addEventListener('click', () => {
        tabButtons.forEach(b => b.classList.remove('active'));
        tabPanels.forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        const panel = document.querySelector(`[data-panel="${btn.dataset.tab}"]`);
        if (panel) panel.classList.add('active');
        currentTab = btn.dataset.tab || 'info';
        const url = new URL(window.location);
        url.searchParams.set('tab', btn.dataset.tab);
        window.history.replaceState({}, '', url);
    }));
    const initialTab = new URL(window.location).searchParams.get('tab');
    const initialButton = initialTab ? document.querySelector(`[data-tab="${initialTab}"]`) : tabButtons[0];
    if (initialButton) initialButton.click();

    // Autocomplete + list render
    const searchInput = document.getElementById('supplier-search');
    const listEl = document.getElementById('supplier-list');
    const archived = '0';
    const detailDataScript = document.getElementById('detail-data');
    let currentDetail = detailDataScript ? JSON.parse(detailDataScript.textContent || '{}') : null;
    let currentSupplierId = currentDetail ? currentDetail.id : null;
    const urlSupplierId = new URL(window.location).searchParams.get('supplier_id');
    const initialSuppliersScript = document.getElementById('initial-suppliers');
    let initialSuppliers = [];
    if (initialSuppliersScript) {
        try {
            initialSuppliers = JSON.parse(initialSuppliersScript.textContent || '[]');
        } catch (e) {
            initialSuppliers = [];
        }
    }

    // Build left-hand list and navigate with a full page load (so URL updates)
    function renderList(items) {
        listEl.innerHTML = '';
        if (!items || !items.length) {
            const empty = document.createElement('div');
            empty.className = 'text-slate-500 text-sm px-2 py-3';
            empty.textContent = 'No suppliers found.';
            listEl.appendChild(empty);
            return;
        }
        items.forEach(item => {
            const a = document.createElement('a');
            a.href = "#";
            a.dataset.id = item.id;
            a.className = 'supplier-card flex items-center justify-between hover:border-indigo-200';
            a.innerHTML = `
                <div>
                    <div class="text-sm font-semibold text-slate-900">${item.name}</div>
                    <div class="text-xs text-slate-500 flex items-center gap-2">
                        ${item.cage_code ? `<span class="font-mono">CAGE: ${item.cage_code}</span>` : ''}
                    </div>
                </div>
                <span class="badge badge-neutral">View</span>
            `;
            a.addEventListener('click', function(ev) {
                ev.preventDefault();
                fetchDetail(item.id, true);
            });
            listEl.appendChild(a);
        });
    }

    function doSearch(term) {
        setSearchLoading(true);
        const params = new URLSearchParams({ q: term || '', archived });
        fetch(`?${params.toString()}`)
            .then(resp => resp.json())
            .then(data => {
                renderList(data.results || []);
                const url = new URL(window.location);
                if (term) url.searchParams.set('q', term); else url.searchParams.delete('q');
                url.searchParams.delete('supplier_id');
                url.searchParams.set('tab', currentTab || 'info');
                window.history.replaceState({}, '', url);
            })
            .catch(() => {
                showToast('Search failed. Please try again.', 'error');
            })
            .finally(() => {
                setSearchLoading(false);
            });
    }

    let debounceTimer;
    searchInput.addEventListener('input', () => {
        const term = searchInput.value.trim();
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => doSearch(term), 200);
    });

    // Allow manual reset of search/list
    const resetBtn = document.createElement('button');
    resetBtn.type = 'button';
    resetBtn.textContent = 'Reset';
    resetBtn.className = 'mt-2 text-xs text-indigo-600 hover:underline';
    resetBtn.addEventListener('click', () => {
        searchInput.value = '';
        renderList(initialSuppliers);
        const url = new URL(window.location);
        url.searchParams.delete('q');
        url.searchParams.delete('supplier_id');
        window.history.replaceState({}, '', url);
    });
    if (searchInput && searchInput.parentElement) {
        searchInput.parentElement.appendChild(resetBtn);
    }

    // Render the main detail pane from a supplier payload
    function setDetail(data) {
        if (!data || !data.id) return;
        currentDetail = data;
        const setText = (id, value) => {
            const el = document.getElementById(id);
            if (el) el.textContent = value;
        };
        setText('detail-name', data.name || 'N/A');
        const statuses = document.getElementById('detail-statuses');
        if (statuses) {
            statuses.innerHTML = '';
            if (data.probation) statuses.innerHTML += '<span class="badge badge-red">Probation</span>';
            if (data.conditional) statuses.innerHTML += '<span class="badge badge-yellow">Conditional</span>';
            if (data.archived) statuses.innerHTML += '<span class="badge badge-muted">Archived</span>';
        }
        setText('detail-cage', data.cage_code || 'N/A');
        const typeSelect = document.getElementById('detail-type-select');
        if (typeSelect) typeSelect.value = data.supplier_type_id || '';
        const packhouseSelect = document.getElementById('detail-packhouse-select');
        if (packhouseSelect) packhouseSelect.value = data.packhouse_id || '';
        const dodaacEl = document.getElementById('detail-dodaac');
        if (dodaacEl) dodaacEl.textContent = data.dodaac || 'N/A';
        setText('detail-phone', data.business_phone || 'No phone');
        setText('detail-email', data.business_email || 'No email');
        setText('detail-fax', data.business_fax || 'No fax');
        setText('detail-address', data.address || 'No address on file');
        setText('detail-notes', data.notes || 'No notes yet');
        const notes2 = document.getElementById('detail-notes-2');
        if (notes2) notes2.textContent = data.notes || 'No notes yet';
        const addrPhys = document.getElementById('detail-addr-physical');
        if (addrPhys) addrPhys.textContent = data.physical_address || 'No address';
        const addrShip = document.getElementById('detail-addr-shipping');
        if (addrShip) addrShip.textContent = data.shipping_address || 'No address';
        const addrBill = document.getElementById('detail-addr-billing');
        if (addrBill) addrBill.textContent = data.billing_address || 'No address';
        currentDetail.physical_address_id = data.physical_address_id;
        currentDetail.shipping_address_id = data.shipping_address_id;
        currentDetail.billing_address_id = data.billing_address_id;
        currentDetail.physical_address_display = data.physical_address_display;
        currentDetail.shipping_address_display = data.shipping_address_display;
        currentDetail.billing_address_display = data.billing_address_display;
        setText('detail-gsi', data.allows_gsi || 'Unknown');
        setText('detail-ppi', data.ppi === true ? 'Yes' : data.ppi === false ? 'No' : 'Unknown');
        setText('detail-iso', data.iso === true ? 'Yes' : data.iso === false ? 'No' : 'Unknown');
        setText('detail-prime', data.prime || '');
        setText('detail-special', data.special_terms || '');
        setText('detail-special-on', data.special_terms_on || '');
        const filesEl = document.getElementById('detail-files-url');
        if (filesEl) {
            if (data.files_url) {
                filesEl.textContent = 'SharePoint Link';
                filesEl.setAttribute('href', data.files_url);
                filesEl.classList.remove('text-slate-500', 'pointer-events-none', 'cursor-not-allowed');
                filesEl.classList.add('text-indigo-600');
            } else {
                filesEl.textContent = 'None provided';
                filesEl.setAttribute('href', '#');
                filesEl.classList.add('text-slate-500', 'pointer-events-none', 'cursor-not-allowed');
                filesEl.classList.remove('text-indigo-600');
            }
        }
        if (primeSelect) primeSelect.value = data.prime != null ? String(data.prime) : '';
        if (ppiSelect) ppiSelect.value = data.ppi === true ? 'true' : data.ppi === false ? 'false' : '';
        if (isoSelect) isoSelect.value = data.iso === true ? 'true' : data.iso === false ? 'false' : '';
        if (gsiSelect) gsiSelect.value = data.allows_gsi_value || 'UNK';
        if (specialTermsSelect) specialTermsSelect.value = data.special_terms_id || '';
        setText('detail-prob-on', data.probation_on || '');
        setText('detail-prob-by', data.probation_by || '');
        setText('detail-cond-on', data.conditional_on || '');
        setText('detail-cond-by', data.conditional_by || '');
        setText('detail-arch-on', data.archived_on || '');
        setText('detail-arch-by', data.archived_by || '');
        setText('detail-contact-name', data.contact_name || '');
        setText('detail-contact-email', data.contact_email || '');
        setText('detail-contact-phone', data.contact_phone || '');

        const contractsEl = document.getElementById('detail-contracts');
        if (contractsEl) {
            if (data.contracts && data.contracts.length) {
                contractsEl.innerHTML = data.contracts.map(c => `
                    <div class="flex justify-between text-sm">
                        <div>
                            <div class="font-semibold">${c.number || 'No Number'}</div>
                            <div class="text-xs text-slate-500">Award: ${c.award_date || 'N/A'}</div>
                        </div>
                        <div class="text-xs text-slate-600">${c.status || ''}</div>
                    </div>
                `).join('');
            } else {
                contractsEl.innerHTML = '<div class="text-sm text-slate-600">No contracts.</div>';
            }
        }

        renderContacts(data.contacts || []);

        const contactsPanel = document.getElementById('detail-contacts');
        if (contactsPanel) {
            if (data.contacts && data.contacts.length) {
                contactsPanel.className = 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3';
                contactsPanel.innerHTML = data.contacts.map(ct => `
                    <div class="border border-slate-200 rounded-md px-3 py-2 bg-slate-50 space-y-1">
                        <div class="font-semibold text-slate-900">
                            ${ct.id ? `<a href="${``.replace('/0/', `/${ct.id}/`)}" class="text-blue-600 hover:text-blue-800">${ct.name || ''}</a>` : (ct.name || '')}
                            ${ct.title ? `<span class="text-xs text-slate-500">(${ct.title})</span>` : ''}
                        </div>
                        <div class="text-sm text-slate-700">
                            ${ct.email ? `<a href="mailto:${ct.email}" class="text-indigo-600 hover:underline">${ct.email}</a>` : '<span class="text-slate-500">No email</span>'}
                        </div>
                        <div class="text-sm text-slate-700">
                            ${ct.phone ? `<a href="tel:${ct.phone}" class="text-indigo-600 hover:underline">${ct.phone}</a>` : '<span class="text-slate-500">No phone</span>'}
                        </div>
                    </div>
                `).join('');
            } else {
                contactsPanel.className = '';
                contactsPanel.innerHTML = '<div class="text-sm text-slate-600">No personnel listed.</div>';
            }
        }

        renderCerts(data.certifications || []);
        renderClasses(data.classifications || []);

        const certsEl = document.getElementById('detail-certs');
        if (certsEl) {
            if (data.certifications && data.certifications.length) {
                certsEl.innerHTML = '<ul class="space-y-1 text-sm">' + data.certifications.map(cert => `
                    <li>${cert.type || ''}${cert.expires ? ` (exp ${cert.expires})` : ''}</li>
                `).join('') + '</ul>';
            } else {
                certsEl.innerHTML = '<div class="text-sm text-slate-600">No certifications.</div>';
            }
        }

        const statsEl = document.getElementById('detail-stats');
        if (statsEl) {
            if (data.stats) {
                statsEl.innerHTML = `
                    <div class="grid grid-cols-2 gap-2 text-sm">
                        <div>Total Contracts: ${data.stats.total_contracts || 0}</div>
                        <div>Active Contracts: ${data.stats.active_contracts || 0}</div>
                        <div>Total Value: ${data.stats.total_value || 0}</div>
                        <div>Yearly Value: ${data.stats.yearly_value || 0}</div>
                    </div>
                `;
            } else {
                statsEl.innerHTML = '<div class="text-sm text-slate-600">No stats.</div>';
            }
        }
    }

    function resetDetailUI() {
        const textTargets = [
            'detail-name', 'detail-cage', 'detail-dodaac', 'detail-phone', 'detail-email', 'detail-fax',
            'detail-address', 'detail-notes', 'detail-notes-2', 'detail-addr-physical', 'detail-addr-shipping', 'detail-addr-billing',
            'detail-gsi', 'detail-ppi', 'detail-iso', 'detail-prime', 'detail-special', 'detail-special-on',
            'detail-prob-on', 'detail-prob-by', 'detail-cond-on', 'detail-cond-by', 'detail-arch-on', 'detail-arch-by',
            'detail-contact-name', 'detail-contact-email', 'detail-contact-phone'
        ];
        textTargets.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.textContent = '';
        });
        const listTargets = [
            'detail-contracts', 'detail-contacts', 'detail-certs', 'detail-classifications', 'detail-stats', 'contacts-list'
        ];
        listTargets.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = '';
        });
    }

    // Fetch detail payload via AJAX (used on initial load when only supplier_id is in URL)
    function fetchDetail(id, updateUrl = false) {
        setDetailLoading(true);
        resetDetailUI();
        const params = new URLSearchParams({ supplier_id: id, ajax: '1' });
        fetch(`${window.location.pathname}?${params.toString()}`, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(async resp => {
                if (!resp.ok) {
                    const text = await resp.text();
                    throw new Error(`HTTP ${resp.status}: ${text.slice(0, 300)}`);
                }
                return resp.json();
            })
            .then(data => {
                setDetail(data);
                currentSupplierId = data.id;
                // highlight selection
                document.querySelectorAll('.supplier-item').forEach(el => {
                    el.classList.toggle('border-indigo-300', el.dataset.id == id);
                    el.classList.toggle('bg-indigo-50', el.dataset.id == id);
                });
                if (updateUrl) {
                    const url = new URL(window.location);
                    url.searchParams.set('supplier_id', id);
                    url.searchParams.set('tab', currentTab || 'info');
                    window.history.replaceState({}, '', url);
                }
            })
            .catch((err) => {
                const message = err && err.message ? err.message : 'Failed to load supplier details.';
                showToast(message, 'error');
                console.error('Supplier detail error', err);
            })
            .finally(() => {
                setDetailLoading(false);
            });
    }

    // Attach click handlers to existing list
    document.querySelectorAll('.supplier-item').forEach(el => {
        el.addEventListener('click', function(ev) {
            ev.preventDefault();
            fetchDetail(this.dataset.id, true);
        });
    });

    // Initialize detail from server payload
    if (currentDetail && currentDetail.id) {
        setDetail(currentDetail);
        currentSupplierId = currentDetail.id || currentSupplierId;
    } else if (urlSupplierId) {
        fetchDetail(urlSupplierId, true);
    }

    // Render contact cards and wire edit/delete actions
    function renderContacts(contacts) {
        currentDetail.contacts = contacts;
        const list = document.getElementById('contacts-list');
        if (!list) return;
        if (!contacts.length) {
            list.className = 'text-slate-500 text-sm';
            list.innerHTML = 'No contacts yet';
            return;
        }
        list.className = 'grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3 text-sm';
        list.innerHTML = contacts.map(ct => `
            <div class="border border-slate-200 rounded-md px-3 py-2 bg-slate-50 contact-row h-full flex flex-col justify-between" data-contact-id="${ct.id || ''}">
                <div>
                    <div class="font-semibold text-slate-900 flex items-center gap-2">
                        ${ct.name || ''}
                        ${ct.title ? `<span class="text-xs text-slate-500">(${ct.title})</span>` : ''}
                    </div>
                    <div class="text-slate-700 text-sm">
                        ${ct.email ? `<a href="mailto:${ct.email}" class="text-indigo-600 hover:underline">${ct.email}</a>` : ''}
                    </div>
                    <div class="text-slate-700 text-sm">
                        ${ct.phone ? `<a href="tel:${ct.phone}" class="text-indigo-600 hover:underline">${ct.phone}</a>` : ''}
                    </div>
                </div>
                <div class="flex items-center gap-2 justify-end mt-2">
                    <button type="button" class="edit-contact-btn text-slate-500 hover:text-indigo-600" title="Edit contact" data-contact-id="${ct.id || ''}" data-contact-name="${ct.name || ''}" data-contact-email="${ct.email || ''}" data-contact-phone="${ct.phone || ''}" data-contact-title="${ct.title || ''}">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
                    </button>
                    <button type="button" class="delete-contact-btn text-red-500 hover:text-red-700" title="Delete contact" data-contact-id="${ct.id || ''}">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                    </button>
                </div>
            </div>
        `).join('');

        list.querySelectorAll('.edit-contact-btn').forEach(btn => {
            btn.addEventListener('click', () => openContactModal({
                id: btn.dataset.contactId,
                name: btn.dataset.contactName,
                email: btn.dataset.contactEmail,
                phone: btn.dataset.contactPhone,
                title: btn.dataset.contactTitle
            }));
        });
        list.querySelectorAll('.delete-contact-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const contactId = btn.dataset.contactId;
                if (!contactId || !currentSupplierId) return;
                
                // Add loading state to the row
                const row = btn.closest('.contact-row');
                if (row) row.style.opacity = '0.5';
                btn.disabled = true;
                
                const deleteUrl = ``.replace('/0/contact/0/', `/${currentSupplierId}/contact/${contactId}/`);
                fetch(deleteUrl, {
                    method: 'POST',
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRFToken': getCookie('csrftoken')
                    }
                })
                .then(resp => resp.json())
                .then(data => {
                    currentSupplierId = data.id;
                    setDetail(data);
                    showToast('Contact deleted.', 'success');
                })
                .catch(() => {
                    showToast('Failed to delete contact.', 'error');
                    if (row) row.style.opacity = '1';
                    btn.disabled = false;
                });
            });
        });
    }

    function renderCerts(certs) {
        const wrap = document.getElementById('detail-certs');
        if (!wrap) return;
        if (!certs.length) {
            wrap.innerHTML = '<div class="text-sm text-slate-600">No certifications.</div>';
            return;
        }
        wrap.innerHTML = certs.map(cert => `
            <div class="flex items-center justify-between border border-slate-200 rounded-md px-3 py-2 bg-slate-50" data-cert-id="${cert.id || ''}">
                <div>
                    <div class="font-semibold text-slate-900">${cert.type || ''}</div>
                    <div class="text-xs text-slate-600">
                        ${cert.date ? `Date: ${cert.date}` : ''}${cert.expires ? `${cert.date ? ' | ' : ''}Exp: ${cert.expires}` : ''}${cert.compliance_status ? `${(cert.date || cert.expires) ? ' | ' : ''}Compliance: ${cert.compliance_status}` : ''}${cert.document_url ? `${(cert.date || cert.expires || cert.compliance_status) ? ' | ' : ''}<a href=\"${cert.document_url}\" target=\"_blank\" class=\"text-indigo-600 hover:text-indigo-800\">View file</a>` : ''}
                    </div>
                </div>
                <button type="button" class="delete-cert-btn text-red-500 hover:text-red-700" title="Delete" data-id="${cert.id || ''}">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                </button>
            </div>
        `).join('');
        wrap.querySelectorAll('.delete-cert-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const cid = btn.dataset.id;
                if (!cid || !currentSupplierId) return;
                
                // Add loading state to the row
                const row = btn.closest('[data-cert-id]');
                if (row) row.style.opacity = '0.5';
                btn.disabled = true;
                
                fetch(``.replace('/0/', `/${currentSupplierId}/`).replace('/0/', `/${cid}/`), {
                    method: 'POST',
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRFToken': getCookie('csrftoken')
                    }
                })
                .then(resp => resp.json())
                .then(() => {
                    refreshDetail();
                    showToast('Certification deleted.', 'success');
                })
                .catch(() => {
                    showToast('Failed to delete certification.', 'error');
                    if (row) row.style.opacity = '1';
                    btn.disabled = false;
                });
            });
        });
    }

    function renderClasses(classes) {
        const wrap = document.getElementById('detail-classifications');
        if (!wrap) return;
        if (!classes.length) {
            wrap.innerHTML = '<div class="text-sm text-slate-600">No classifications.</div>';
            return;
        }
        wrap.innerHTML = classes.map(c => `
            <div class="flex items-center justify-between border border-slate-200 rounded-md px-3 py-2 bg-slate-50" data-class-id="${c.id || ''}">
                <div>
                    <div class="font-semibold text-slate-900">${c.type || ''}</div>
                    <div class="text-xs text-slate-600">
                        ${c.date ? `Date: ${c.date}` : ''}${c.expires ? `${c.date ? ' | ' : ''}Exp: ${c.expires}` : ''}${c.document_url ? `${(c.date || c.expires) ? ' | ' : ''}<a href=\"${c.document_url}\" target=\"_blank\" class=\"text-indigo-600 hover:text-indigo-800\">View file</a>` : ''}
                    </div>
                </div>
                <button type="button" class="delete-class-btn text-red-500 hover:text-red-700" title="Delete" data-id="${c.id || ''}">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                </button>
            </div>
        `).join('');
        wrap.querySelectorAll('.delete-class-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const cid = btn.dataset.id;
                if (!cid || !currentSupplierId) return;
                
                // Add loading state to the row
                const row = btn.closest('[data-class-id]');
                if (row) row.style.opacity = '0.5';
                btn.disabled = true;
                
                fetch(``.replace('/0/', `/${currentSupplierId}/`).replace('/0/', `/${cid}/`), {
                    method: 'POST',
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRFToken': getCookie('csrftoken')
                    }
                })
                .then(resp => resp.json())
                .then(() => {
                    refreshDetail();
                    showToast('Classification deleted.', 'success');
                })
                .catch(() => {
                    showToast('Failed to delete classification.', 'error');
                    if (row) row.style.opacity = '1';
                    btn.disabled = false;
                });
            });
        });
    }

    function refreshDetail(showOverlay = false) {
        if (!currentSupplierId) return;
        if (showOverlay) setDetailLoading(true);
        const params = new URLSearchParams({ supplier_id: currentSupplierId, ajax: '1' });
        fetch(`${window.location.pathname}?${params.toString()}`, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(resp => resp.json())
            .then(data => {
                setDetail(data);
            })
            .catch(() => {
                showToast('Failed to refresh data.', 'error');
            })
            .finally(() => {
                if (showOverlay) setDetailLoading(false);
            });
    }

    // Toggle buttons
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
    // Name/CAGE/DODAAC quick edit modal
    const nameModal = document.getElementById('name-edit-modal');
    const editNameBtn = document.getElementById('edit-name-btn');
    const nameInput = document.getElementById('name-input');
    const cageInput = document.getElementById('cage-input');
    const dodaacInput = document.getElementById('dodaac-input');
    const nameSaveBtn = document.getElementById('name-modal-save');
    const nameCancelBtn = document.getElementById('name-modal-cancel');
    const nameCloseBtn = document.getElementById('name-modal-close');
    const addressModal = document.getElementById('address-modal');
    const addressSelect = document.getElementById('address-select');
    const addressLine1 = document.getElementById('address-line1');
    const addressLine2 = document.getElementById('address-line2');
    const addressCity = document.getElementById('address-city');
    const addressState = document.getElementById('address-state');
    const addressZip = document.getElementById('address-zip');
    const addressSaveBtn = document.getElementById('address-modal-save');
    const addressCancelBtn = document.getElementById('address-modal-cancel');
    const addressCloseBtn = document.getElementById('address-modal-close');
    const contactModal = document.getElementById('contact-modal');
    const contactIdInput = document.getElementById('contact-id');
    const contactNameInput = document.getElementById('contact-name');
    const contactEmailInput = document.getElementById('contact-email');
    const contactPhoneInput = document.getElementById('contact-phone');
    const contactTitleInput = document.getElementById('contact-title');
    const contactSaveBtn = document.getElementById('contact-modal-save');
    const contactCancelBtn = document.getElementById('contact-modal-cancel');
    const contactCloseBtn = document.getElementById('contact-modal-close');
    const addContactBtn = document.getElementById('add-contact-btn');
    const notesModal = document.getElementById('notes-modal');
    const notesInput = document.getElementById('notes-input');
    const notesSaveBtn = document.getElementById('notes-modal-save');
    const notesCancelBtn = document.getElementById('notes-modal-cancel');
    const notesCloseBtn = document.getElementById('notes-modal-close');
    const editNotesBtn = document.getElementById('edit-notes-btn');
    const editNotesBtn2 = document.getElementById('edit-notes-btn-2');
    const filesModal = document.getElementById('files-modal');
    const filesInput = document.getElementById('files-input');
    const filesSaveBtn = document.getElementById('files-modal-save');
    const filesCancelBtn = document.getElementById('files-modal-cancel');
    const filesCloseBtn = document.getElementById('files-modal-close');
    const editFilesBtn = document.getElementById('edit-files-btn');
    const certModal = document.getElementById('cert-modal');
    const certTypeInput = document.getElementById('cert-type-input');
    const certDateInput = document.getElementById('cert-date-input');
    const certExpInput = document.getElementById('cert-exp-input');
    const certFileInput = document.getElementById('cert-file-input');
    const certComplianceInput = document.getElementById('cert-compliance-input');
    const certSaveBtn = document.getElementById('cert-modal-save');
    const certCancelBtn = document.getElementById('cert-modal-cancel');
    const certCloseBtn = document.getElementById('cert-modal-close');
    const openCertBtn = document.getElementById('open-cert-modal');
    const classModal = document.getElementById('class-modal');
    const classTypeInput = document.getElementById('class-type-input');
    const classDateInput = document.getElementById('class-date-input');
    const classExpInput = document.getElementById('class-exp-input');
    const classFileInput = document.getElementById('class-file-input');
    const classSaveBtn = document.getElementById('class-modal-save');
    const classCancelBtn = document.getElementById('class-modal-cancel');
    const classCloseBtn = document.getElementById('class-modal-close');
    const openClassBtn = document.getElementById('open-class-modal');
    const supplierTypeSelect = document.getElementById('detail-type-select');
    const packhouseSelectEl = document.getElementById('detail-packhouse-select');
    const primeSelect = document.getElementById('prime-select');
    const ppiSelect = document.getElementById('ppi-select');
    const isoSelect = document.getElementById('iso-select');
    const gsiSelect = document.getElementById('gsi-select');
    const specialTermsSelect = document.getElementById('special-terms-select');
    let activeAddressField = null;
    let addressesCache = [];

    function populateNameModal() {
        if (!currentDetail) return;
        if (nameInput) nameInput.value = currentDetail.name || '';
        if (cageInput) cageInput.value = currentDetail.cage_code || '';
        if (dodaacInput) dodaacInput.value = currentDetail.dodaac || '';
    }

    function openNameModal() {
        if (!currentSupplierId || !nameModal) return;
        populateNameModal();
        nameModal.classList.remove('hidden');
        nameModal.classList.add('flex');
    }

    function closeNameModal() {
        if (!nameModal) return;
        nameModal.classList.add('hidden');
        nameModal.classList.remove('flex');
        if (nameSaveBtn) nameSaveBtn.disabled = false;
    }

    [nameCancelBtn, nameCloseBtn].forEach(btn => {
        if (btn) btn.addEventListener('click', closeNameModal);
    });
    if (editNameBtn) editNameBtn.addEventListener('click', openNameModal);

    if (nameSaveBtn) {
        nameSaveBtn.addEventListener('click', function() {
            if (!currentSupplierId) return;
            setButtonLoading(nameSaveBtn, true);
            fetch(``.replace('0', currentSupplierId), {
                method: 'POST',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: new URLSearchParams({
                    name: nameInput ? nameInput.value : '',
                    cage_code: cageInput ? cageInput.value : '',
                    dodaac: dodaacInput ? dodaacInput.value : ''
                })
            })
            .then(resp => {
                if (!resp.ok) throw new Error('Save failed');
                return resp.json();
            })
            .then(data => {
                currentSupplierId = data.id;
                setDetail(data);
                const listTitle = document.querySelector(`.supplier-item[data-id="${currentSupplierId}"] .text-sm.font-semibold`);
                if (listTitle) {
                    listTitle.textContent = data.cage_code ? `${data.name || 'N/A'} (${data.cage_code})` : (data.name || 'N/A');
                }
                closeNameModal();
                showToast('Supplier updated successfully!', 'success');
            })
            .catch(() => {
                showToast('Failed to save changes. Please try again.', 'error');
            })
            .finally(() => {
                setButtonLoading(nameSaveBtn, false);
            });
        });
    }

    function populateAddressSelect(addresses) {
        if (!addressSelect) return;
        addressSelect.innerHTML = '<option value="">-- Select address --</option>';
        addresses.forEach(addr => {
            const opt = document.createElement('option');
            opt.value = addr.id;
            opt.textContent = addr.display || '';
            addressSelect.appendChild(opt);
        });
    }

    function fetchAddresses(query) {
        const params = new URLSearchParams();
        if (query) params.append('q', query);
        fetch(`?${params.toString()}`)
            .then(resp => resp.json())
            .then(data => {
                addressesCache = data.results || [];
                populateAddressSelect(addressesCache);
            })
            .catch(() => {});
    }

    function populateAddressFields(field) {
        if (!currentDetail) return;
        const addrObj = currentDetail[`${field}_address_obj`];
        if (addressSelect) addressSelect.value = addrObj && addrObj.id ? addrObj.id : '';
        if (addressLine1) addressLine1.value = addrObj?.line1 || '';
        if (addressLine2) addressLine2.value = addrObj?.line2 || '';
        if (addressCity) addressCity.value = addrObj?.city || '';
        if (addressState) addressState.value = addrObj?.state || '';
        if (addressZip) addressZip.value = addrObj?.zip || '';
    }

    function openAddressModal(field) {
        if (!addressModal || !field || !currentSupplierId) return;
        activeAddressField = field;
        fetchAddresses();
        populateAddressFields(field);
        addressModal.classList.remove('hidden');
        addressModal.classList.add('flex');
    }

    function closeAddressModal() {
        if (!addressModal) return;
        addressModal.classList.add('hidden');
        addressModal.classList.remove('flex');
        if (addressSaveBtn) addressSaveBtn.disabled = false;
        activeAddressField = null;
    }

    [addressCancelBtn, addressCloseBtn].forEach(btn => {
        if (btn) btn.addEventListener('click', closeAddressModal);
    });

    document.querySelectorAll('.edit-address-btn').forEach(btn => {
        btn.addEventListener('click', () => openAddressModal(btn.dataset.field));
    });

    if (addressSaveBtn) {
        addressSaveBtn.addEventListener('click', function() {
            if (!currentSupplierId || !activeAddressField) return;
            setButtonLoading(addressSaveBtn, true);
            fetch(``.replace('0', currentSupplierId), {
                method: 'POST',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: new URLSearchParams({
                    field: activeAddressField,
                    address_id: addressSelect ? addressSelect.value : '',
                    line1: addressLine1 ? addressLine1.value : '',
                    line2: addressLine2 ? addressLine2.value : '',
                    city: addressCity ? addressCity.value : '',
                    state: addressState ? addressState.value : '',
                    zip: addressZip ? addressZip.value : '',
                })
            })
            .then(resp => resp.json())
            .then(data => {
                currentSupplierId = data.id;
                setDetail(data);
                closeAddressModal();
                showToast('Address updated successfully!', 'success');
            })
            .catch(() => {
                showToast('Failed to save address. Please try again.', 'error');
            })
            .finally(() => {
                setButtonLoading(addressSaveBtn, false);
            });
        });
    }

    function openContactModal(contact = {}) {
        if (!contactModal || !currentSupplierId) return;
        if (contactIdInput) contactIdInput.value = contact.id || '';
        if (contactNameInput) contactNameInput.value = contact.name || '';
        if (contactEmailInput) contactEmailInput.value = contact.email || '';
        if (contactPhoneInput) contactPhoneInput.value = contact.phone || '';
        if (contactTitleInput) contactTitleInput.value = contact.title || '';
        contactModal.classList.remove('hidden');
        contactModal.classList.add('flex');
    }

    function closeContactModal() {
        if (!contactModal) return;
        contactModal.classList.add('hidden');
        contactModal.classList.remove('flex');
        if (contactSaveBtn) contactSaveBtn.disabled = false;
    }

    [contactCancelBtn, contactCloseBtn].forEach(btn => {
        if (btn) btn.addEventListener('click', closeContactModal);
    });

    if (addContactBtn) addContactBtn.addEventListener('click', () => openContactModal({}));

    if (contactSaveBtn) {
        contactSaveBtn.addEventListener('click', function() {
            if (!currentSupplierId) return;
            setButtonLoading(contactSaveBtn, true);
            fetch(``.replace('0', currentSupplierId), {
                method: 'POST',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: new URLSearchParams({
                    contact_id: contactIdInput ? contactIdInput.value : '',
                    name: contactNameInput ? contactNameInput.value : '',
                    email: contactEmailInput ? contactEmailInput.value : '',
                    phone: contactPhoneInput ? contactPhoneInput.value : '',
                    title: contactTitleInput ? contactTitleInput.value : '',
                })
            })
            .then(resp => resp.json())
            .then(data => {
                currentSupplierId = data.id;
                setDetail(data);
                closeContactModal();
                if (contactPhoneInput) contactPhoneInput.value = formatPhone(contactPhoneInput.value);
                showToast('Contact saved successfully!', 'success');
            })
            .catch(() => {
                showToast('Failed to save contact. Please try again.', 'error');
            })
            .finally(() => {
                setButtonLoading(contactSaveBtn, false);
            });
        });
    }

    function updateSelects(payload, triggerSelect = null) {
        if (!currentSupplierId) return;
        if (triggerSelect) setSelectLoading(triggerSelect, true);
        fetch(``.replace('0', currentSupplierId), {
            method: 'POST',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: new URLSearchParams(payload)
        })
        .then(resp => resp.json())
        .then(data => {
            currentSupplierId = data.id;
            setDetail(data);
            showToast('Updated successfully!', 'success');
        })
        .catch(() => {
            showToast('Failed to update. Please try again.', 'error');
        })
        .finally(() => {
            if (triggerSelect) setSelectLoading(triggerSelect, false);
        });
    }

    if (supplierTypeSelect) {
        supplierTypeSelect.addEventListener('change', () => {
            updateSelects({ supplier_type_id: supplierTypeSelect.value || '' }, supplierTypeSelect);
        });
    }

    if (packhouseSelectEl) {
        packhouseSelectEl.addEventListener('change', () => {
            updateSelects({ packhouse_id: packhouseSelectEl.value || '' }, packhouseSelectEl);
        });
    }

    function updateCompliance(payload, triggerSelect = null) {
        if (!currentSupplierId) return;
        if (triggerSelect) setSelectLoading(triggerSelect, true);
        fetch(``.replace('0', currentSupplierId), {
            method: 'POST',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: new URLSearchParams(payload)
        })
        .then(resp => resp.json())
        .then(data => {
            currentSupplierId = data.id;
            setDetail(data);
            showToast('Compliance updated!', 'success');
        })
        .catch(() => {
            showToast('Failed to update compliance.', 'error');
        })
        .finally(() => {
            if (triggerSelect) setSelectLoading(triggerSelect, false);
        });
    }

    if (primeSelect) {
        primeSelect.addEventListener('change', () => {
            updateCompliance({ prime: primeSelect.value || '' }, primeSelect);
        });
    }
    if (ppiSelect) {
        ppiSelect.addEventListener('change', () => {
            updateCompliance({ ppi: ppiSelect.value || '' }, ppiSelect);
        });
    }
    if (isoSelect) {
        isoSelect.addEventListener('change', () => {
            updateCompliance({ iso: isoSelect.value || '' }, isoSelect);
        });
    }
    if (gsiSelect) {
        gsiSelect.addEventListener('change', () => {
            updateCompliance({ allows_gsi: gsiSelect.value || 'UNK' }, gsiSelect);
        });
    }
    if (specialTermsSelect) {
        specialTermsSelect.addEventListener('change', () => {
            updateCompliance({ special_terms_id: specialTermsSelect.value || '' }, specialTermsSelect);
        });
    }

    // QMS modals
    function openCertModal() {
        if (!certModal) return;
        if (certTypeInput) certTypeInput.value = '';
        if (certDateInput) certDateInput.value = '';
        if (certExpInput) certExpInput.value = '';
        if (certComplianceInput) certComplianceInput.value = '';
        if (certFileInput) certFileInput.value = '';
        certModal.classList.remove('hidden');
        certModal.classList.add('flex');
    }
    function closeCertModal() {
        if (!certModal) return;
        certModal.classList.add('hidden');
        certModal.classList.remove('flex');
        if (certSaveBtn) certSaveBtn.disabled = false;
    }
    [certCancelBtn, certCloseBtn].forEach(btn => {
        if (btn) btn.addEventListener('click', closeCertModal);
    });
    if (openCertBtn) openCertBtn.addEventListener('click', openCertModal);
    if (certSaveBtn) {
        certSaveBtn.addEventListener('click', function() {
            if (!currentSupplierId || !certTypeInput || !certTypeInput.value) return;
            setButtonLoading(certSaveBtn, true);
            const formData = new FormData();
            formData.append('certification_type', certTypeInput.value);
            formData.append('certification_date', certDateInput ? certDateInput.value : '');
            formData.append('certification_expiration', certExpInput ? certExpInput.value : '');
            formData.append('compliance_status', certComplianceInput ? certComplianceInput.value : '');
            if (certFileInput && certFileInput.files && certFileInput.files[0]) {
                formData.append('file', certFileInput.files[0]);
            }
            fetch(``.replace('0', currentSupplierId), {
                method: 'POST',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: formData
            })
            .then(resp => resp.json())
            .then(() => {
                closeCertModal();
                refreshDetail();
                showToast('Certification added successfully!', 'success');
            })
            .catch(() => {
                showToast('Failed to add certification.', 'error');
            })
            .finally(() => {
                setButtonLoading(certSaveBtn, false);
            });
        });
    }

    function openClassModal() {
        if (!classModal) return;
        if (classTypeInput) classTypeInput.value = '';
        if (classDateInput) classDateInput.value = '';
        if (classExpInput) classExpInput.value = '';
        if (classFileInput) classFileInput.value = '';
        classModal.classList.remove('hidden');
        classModal.classList.add('flex');
    }
    function closeClassModal() {
        if (!classModal) return;
        classModal.classList.add('hidden');
        classModal.classList.remove('flex');
        if (classSaveBtn) classSaveBtn.disabled = false;
    }
    [classCancelBtn, classCloseBtn].forEach(btn => {
        if (btn) btn.addEventListener('click', closeClassModal);
    });
    if (openClassBtn) openClassBtn.addEventListener('click', openClassModal);
    if (classSaveBtn) {
        classSaveBtn.addEventListener('click', function() {
            if (!currentSupplierId || !classTypeInput || !classTypeInput.value) return;
            setButtonLoading(classSaveBtn, true);
            const formData = new FormData();
            formData.append('classification_type', classTypeInput.value);
            formData.append('classification_date', classDateInput ? classDateInput.value : '');
            formData.append('expiration_date', classExpInput ? classExpInput.value : '');
            if (classFileInput && classFileInput.files && classFileInput.files[0]) {
                formData.append('file', classFileInput.files[0]);
            }
            fetch(``.replace('0', currentSupplierId), {
                method: 'POST',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: formData
            })
            .then(resp => resp.json())
            .then(() => {
                closeClassModal();
                refreshDetail();
                showToast('Classification added successfully!', 'success');
            })
            .catch(() => {
                showToast('Failed to add classification.', 'error');
            })
            .finally(() => {
                setButtonLoading(classSaveBtn, false);
            });
        });
    }

    function openNotesModal() {
        if (!notesModal || !notesInput) return;
        notesInput.value = (currentDetail && currentDetail.notes) || '';
        notesModal.classList.remove('hidden');
        notesModal.classList.add('flex');
    }

    function closeNotesModal() {
        if (!notesModal) return;
        notesModal.classList.add('hidden');
        notesModal.classList.remove('flex');
        if (notesSaveBtn) notesSaveBtn.disabled = false;
    }

    [notesCancelBtn, notesCloseBtn].forEach(btn => {
        if (btn) btn.addEventListener('click', closeNotesModal);
    });
    [editNotesBtn, editNotesBtn2].forEach(btn => {
        if (btn) btn.addEventListener('click', openNotesModal);
    });

    if (notesSaveBtn) {
        notesSaveBtn.addEventListener('click', function() {
            if (!currentSupplierId) return;
            setButtonLoading(notesSaveBtn, true);
            fetch(``.replace('0', currentSupplierId), {
                method: 'POST',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: new URLSearchParams({
                    notes: notesInput ? notesInput.value : ''
                })
            })
            .then(resp => resp.json())
            .then(data => {
                currentSupplierId = data.id;
                setDetail(data);
                closeNotesModal();
                showToast('Notes saved successfully!', 'success');
            })
            .catch(() => {
                showToast('Failed to save notes.', 'error');
            })
            .finally(() => {
                setButtonLoading(notesSaveBtn, false);
            });
        });
    }

    function openFilesModal() {
        if (!filesModal || !filesInput) return;
        filesInput.value = (currentDetail && currentDetail.files_url) || '';
        filesModal.classList.remove('hidden');
        filesModal.classList.add('flex');
    }

    function closeFilesModal() {
        if (!filesModal) return;
        filesModal.classList.add('hidden');
        filesModal.classList.remove('flex');
        if (filesSaveBtn) filesSaveBtn.disabled = false;
    }

    [filesCancelBtn, filesCloseBtn].forEach(btn => {
        if (btn) btn.addEventListener('click', closeFilesModal);
    });
    if (editFilesBtn) editFilesBtn.addEventListener('click', openFilesModal);

    if (filesSaveBtn) {
        filesSaveBtn.addEventListener('click', function() {
            if (!currentSupplierId) return;
            setButtonLoading(filesSaveBtn, true);
            fetch(``.replace('0', currentSupplierId), {
                method: 'POST',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: new URLSearchParams({
                    files_url: filesInput ? filesInput.value : ''
                })
            })
            .then(resp => resp.json())
            .then(data => {
                currentSupplierId = data.id;
                setDetail(data);
                closeFilesModal();
                showToast('Files URL saved successfully!', 'success');
            })
            .catch(() => {
                showToast('Failed to save files URL.', 'error');
            })
            .finally(() => {
                setButtonLoading(filesSaveBtn, false);
            });
        });
    }

    // Simple phone mask for contact phone input
    function formatPhone(value) {
        const digits = (value || '').replace(/\D/g, '').slice(0, 10);
        const parts = [];
        if (digits.length > 0) parts.push('(' + digits.slice(0, Math.min(3, digits.length)));
        if (digits.length >= 4) parts[0] += ') ';
        if (digits.length > 3) parts.push(digits.slice(3, Math.min(6, digits.length)));
        if (digits.length >= 7) parts.push('-' + digits.slice(6, Math.min(10, digits.length)));
        return parts.join('');
    }
    if (contactPhoneInput) {
        contactPhoneInput.addEventListener('input', () => {
            const caretPos = contactPhoneInput.selectionStart;
            const formatted = formatPhone(contactPhoneInput.value);
            contactPhoneInput.value = formatted;
            contactPhoneInput.setSelectionRange(caretPos, caretPos);
        });
    }

    document.querySelectorAll('.toggle-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            if (this.disabled || this.dataset.disabled === 'true') return;
            const field = this.dataset.flag;
            if (!currentSupplierId || !field) return;
            
            // Disable button during request
            this.disabled = true;
            const originalText = this.textContent;
            this.innerHTML = '<div class="spinner spinner-dark" style="width: 12px; height: 12px;"></div>';
            
            fetch(``.replace('0', currentSupplierId), {
                method: 'POST',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: new URLSearchParams({ field })
            })
            .then(resp => resp.json())
            .then(data => {
                currentSupplierId = data.id;
                setDetail(data);
                document.querySelectorAll('.toggle-btn').forEach(b => {
                    const f = b.dataset.flag;
                    b.classList.toggle('active', data[f] === true);
                });
                const statusText = data[field] ? 'enabled' : 'disabled';
                showToast(`${field.charAt(0).toUpperCase() + field.slice(1)} ${statusText}!`, 'success');
            })
            .catch(() => {
                showToast('Failed to update status.', 'error');
            })
            .finally(() => {
                this.disabled = false;
                this.textContent = originalText;
            });
        });
    });
});
