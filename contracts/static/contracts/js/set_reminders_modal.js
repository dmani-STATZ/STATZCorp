(function () {
    'use strict';

    var root = document.getElementById('setRemindersRoot');
    if (!root) {
        return;
    }

    var presetsUrl = root.dataset.presetsUrl;
    var bulkUrl = root.dataset.bulkUrl;
    var pageContractId = parseInt(root.dataset.contractId, 10);
    var defaultContractNumber = root.dataset.contractNumber || '';

    var promptModalEl = document.getElementById('promptSetRemindersModal');
    var setModalEl = document.getElementById('setRemindersModal');
    var tableBody = document.getElementById('setRemindersTableBody');
    var loadError = document.getElementById('setRemindersLoadError');
    var loadingEl = document.getElementById('setRemindersLoading');
    var tableWrap = document.getElementById('setRemindersTableWrap');
    var saveBtn = document.getElementById('setRemindersSaveBtn');
    var saveBtnLabel = document.getElementById('setRemindersSaveBtnLabel');
    var saveSpinner = document.getElementById('setRemindersSaveSpinner');
    var modalTitle = document.getElementById('setRemindersModalLabel');
    var addRowBtn = document.getElementById('setRemindersAddRowBtn');
    var promptConfirmBtn = document.getElementById('promptSetRemindersConfirmBtn');

    var targets = [];
    var activeContractId = null;
    var pendingToggleContractId = null;

    function getCsrfToken() {
        if (typeof window.getCookie === 'function') {
            var fromCookie = window.getCookie('csrftoken');
            if (fromCookie) {
                return fromCookie;
            }
        }
        var fromForm = document.querySelector('#csrf-form [name=csrfmiddlewaretoken]');
        if (fromForm && fromForm.value) {
            return fromForm.value;
        }
        var match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? match[1] : '';
    }

    function removeIconSvg() {
        return '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M4.646 4.646a.5.5 0 0 1 .708 0L8 7.293l2.646-2.647a.5.5 0 0 1 .708.708L8.707 8l2.647 2.646a.5.5 0 0 1-.708.708L8 8.707l-2.646 2.647a.5.5 0 0 1-.708-.708L7.293 8 4.646 5.354a.5.5 0 0 1 0-.708z"/></svg>';
    }

    function buildTargetSelect(selectedType, selectedId) {
        var select = document.createElement('select');
        select.className = 'form-select form-select-sm set-reminders-target-select';
        select.required = true;
        targets.forEach(function (t) {
            var opt = document.createElement('option');
            opt.value = t.target_type + ':' + t.target_id;
            opt.textContent = t.target_label;
            if (t.target_type === selectedType && String(t.target_id) === String(selectedId)) {
                opt.selected = true;
            }
            select.appendChild(opt);
        });
        return select;
    }

    function parseTargetSelect(select) {
        var parts = select.value.split(':');
        return { target_type: parts[0], target_id: parseInt(parts[1], 10) };
    }

    function clearRowValidation(row) {
        row.querySelectorAll('.is-invalid').forEach(function (el) {
            el.classList.remove('is-invalid');
        });
        row.querySelectorAll('.invalid-feedback').forEach(function (el) {
            el.remove();
        });
    }

    function setRowError(row, message) {
        var field = row.querySelector('.set-reminders-date-input')
            || row.querySelector('.set-reminders-label-input')
            || row.querySelector('.set-reminders-target-select');
        if (!field) {
            return;
        }
        field.classList.add('is-invalid');
        var fb = document.createElement('div');
        fb.className = 'invalid-feedback d-block';
        fb.textContent = message;
        field.parentNode.appendChild(fb);
    }

    function updateSaveCount() {
        var checked = tableBody.querySelectorAll('tr.set-reminders-row:not(.set-reminders-row-muted) input.set-reminders-check:checked');
        var n = checked.length;
        saveBtnLabel.textContent = 'Save Reminders (' + n + ')';
        if (!loadError.classList.contains('d-none')) {
            saveBtn.disabled = true;
            return;
        }
        if (tableWrap.classList.contains('d-none')) {
            saveBtn.disabled = true;
            return;
        }
        saveBtn.disabled = n === 0;
    }

    function bindRowInteractions(row) {
        var check = row.querySelector('.set-reminders-check');
        if (check) {
            check.addEventListener('change', updateSaveCount);
        }
        var removeBtn = row.querySelector('.set-reminders-remove-btn');
        if (removeBtn) {
            removeBtn.addEventListener('click', function () {
                row.remove();
                updateSaveCount();
            });
        }
    }

    function appendPresetRow(rowData) {
        var tr = document.createElement('tr');
        tr.className = 'set-reminders-row';
        if (rowData.already_set) {
            tr.classList.add('set-reminders-row-muted', 'text-body-secondary');
        }

        tr.dataset.presetKey = rowData.preset_key;
        tr.dataset.rowKind = 'preset';
        tr.dataset.label = rowData.label;

        var tdCheck = document.createElement('td');
        tdCheck.className = 'text-center';
        var check = document.createElement('input');
        check.type = 'checkbox';
        check.className = 'form-check-input set-reminders-check';
        check.checked = rowData.default_checked && !rowData.already_set;
        check.disabled = rowData.already_set;
        tdCheck.appendChild(check);
        tr.appendChild(tdCheck);

        var tdLabel = document.createElement('td');
        tdLabel.textContent = rowData.label;
        if (rowData.already_set) {
            var badge = document.createElement('span');
            badge.className = 'badge bg-secondary ms-2';
            badge.textContent = 'Already set';
            tdLabel.appendChild(badge);
        } else if (rowData.is_past) {
            var pastBadge = document.createElement('span');
            pastBadge.className = 'badge bg-warning text-dark ms-2';
            pastBadge.textContent = 'Past date';
            tdLabel.appendChild(pastBadge);
        }
        tr.appendChild(tdLabel);

        var tdTarget = document.createElement('td');
        var targetSelect = buildTargetSelect(rowData.target_type, rowData.target_id);
        if (rowData.already_set) {
            targetSelect.disabled = true;
        }
        tdTarget.appendChild(targetSelect);
        tr.appendChild(tdTarget);

        var tdDate = document.createElement('td');
        var dateInput = document.createElement('input');
        dateInput.type = 'date';
        dateInput.className = 'form-control form-control-sm set-reminders-date-input';
        dateInput.value = rowData.reminder_date || '';
        dateInput.required = true;
        if (rowData.already_set) {
            dateInput.disabled = true;
        }
        tdDate.appendChild(dateInput);
        tr.appendChild(tdDate);

        var tdRemove = document.createElement('td');
        tdRemove.className = 'text-end';
        if (!rowData.already_set && !rowData.protected) {
            var removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'btn btn-link btn-sm text-danger set-reminders-remove-btn p-0';
            removeBtn.setAttribute('aria-label', 'Remove row');
            removeBtn.innerHTML = removeIconSvg();
            tdRemove.appendChild(removeBtn);
        }
        tr.appendChild(tdRemove);

        tableBody.appendChild(tr);
        bindRowInteractions(tr);
    }

    function appendCustomRow() {
        var tr = document.createElement('tr');
        tr.className = 'set-reminders-row';
        tr.dataset.presetKey = 'custom';
        tr.dataset.rowKind = 'custom';

        var tdCheck = document.createElement('td');
        tdCheck.className = 'text-center';
        var check = document.createElement('input');
        check.type = 'checkbox';
        check.className = 'form-check-input set-reminders-check';
        check.checked = true;
        tdCheck.appendChild(check);
        tr.appendChild(tdCheck);

        var tdLabel = document.createElement('td');
        var labelInput = document.createElement('input');
        labelInput.type = 'text';
        labelInput.maxLength = 200;
        labelInput.required = true;
        labelInput.placeholder = 'Reminder label';
        labelInput.className = 'form-control form-control-sm set-reminders-label-input';
        tdLabel.appendChild(labelInput);
        tr.appendChild(tdLabel);

        var tdTarget = document.createElement('td');
        var contractTarget = targets.find(function (t) { return t.target_type === 'contract'; });
        tdTarget.appendChild(buildTargetSelect(
            contractTarget ? contractTarget.target_type : 'contract',
            contractTarget ? contractTarget.target_id : pageContractId
        ));
        tr.appendChild(tdTarget);

        var tdDate = document.createElement('td');
        var dateInput = document.createElement('input');
        dateInput.type = 'date';
        dateInput.className = 'form-control form-control-sm set-reminders-date-input';
        dateInput.required = true;
        tdDate.appendChild(dateInput);
        tr.appendChild(tdDate);

        var tdRemove = document.createElement('td');
        tdRemove.className = 'text-end';
        var removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'btn btn-link btn-sm text-danger set-reminders-remove-btn p-0';
        removeBtn.setAttribute('aria-label', 'Remove row');
        removeBtn.innerHTML = removeIconSvg();
        tdRemove.appendChild(removeBtn);
        tr.appendChild(tdRemove);

        tableBody.appendChild(tr);
        bindRowInteractions(tr);
        updateSaveCount();
    }

    function resetModalState() {
        tableBody.innerHTML = '';
        loadError.classList.add('d-none');
        loadingEl.classList.add('d-none');
        tableWrap.classList.add('d-none');
        saveBtn.disabled = true;
        saveSpinner.classList.add('d-none');
        saveBtnLabel.textContent = 'Save Reminders (0)';
    }

    function loadPresets(contractId, contractNumber) {
        resetModalState();
        activeContractId = contractId;
        modalTitle.textContent = 'Set Reminders — ' + (contractNumber || defaultContractNumber);
        loadingEl.classList.remove('d-none');
        bootstrap.Modal.getOrCreateInstance(setModalEl).show();

        fetch(presetsUrl, {
            method: 'GET',
            headers: { 'Accept': 'application/json' },
            credentials: 'same-origin',
        })
            .then(function (response) {
                if (!response.ok) {
                    throw new Error('load failed');
                }
                return response.json();
            })
            .then(function (data) {
                if (!data.ok) {
                    throw new Error('load failed');
                }
                targets = data.targets || [];
                loadingEl.classList.add('d-none');
                tableWrap.classList.remove('d-none');
                (data.rows || []).forEach(appendPresetRow);
                updateSaveCount();
            })
            .catch(function () {
                loadingEl.classList.add('d-none');
                loadError.classList.remove('d-none');
                saveBtn.disabled = true;
            });
    }

    function validateCheckedRows() {
        var valid = true;
        var rows = tableBody.querySelectorAll('tr.set-reminders-row');
        rows.forEach(function (row) {
            clearRowValidation(row);
            var check = row.querySelector('.set-reminders-check');
            if (!check || !check.checked || check.disabled) {
                return;
            }
            var dateInput = row.querySelector('.set-reminders-date-input');
            if (!dateInput || !dateInput.value) {
                setRowError(row, 'Date is required.');
                valid = false;
            }
            if (row.dataset.rowKind === 'custom') {
                var labelInput = row.querySelector('.set-reminders-label-input');
                if (!labelInput || !labelInput.value.trim()) {
                    setRowError(row, 'Label is required.');
                    valid = false;
                }
            }
        });
        return valid;
    }

    function collectPayloadRows() {
        var payloadRows = [];
        var indexMap = [];
        var rows = tableBody.querySelectorAll('tr.set-reminders-row');
        rows.forEach(function (row) {
            var check = row.querySelector('.set-reminders-check');
            if (!check || !check.checked || check.disabled) {
                return;
            }
            var target = parseTargetSelect(row.querySelector('.set-reminders-target-select'));
            var dateVal = row.querySelector('.set-reminders-date-input').value;
            var label;
            if (row.dataset.rowKind === 'custom') {
                label = row.querySelector('.set-reminders-label-input').value.trim();
            } else {
                label = (row.dataset.label || '').trim();
            }
            indexMap.push({ domRow: row, payloadIndex: payloadRows.length });
            payloadRows.push({
                preset_key: row.dataset.presetKey || 'custom',
                label: label,
                target_type: target.target_type,
                target_id: target.target_id,
                reminder_date: dateVal,
            });
        });
        return { payloadRows: payloadRows, indexMap: indexMap };
    }

    function saveReminders() {
        if (!validateCheckedRows()) {
            return;
        }
        var collected = collectPayloadRows();
        if (collected.payloadRows.length === 0) {
            return;
        }

        saveBtn.disabled = true;
        saveSpinner.classList.remove('d-none');

        fetch(bulkUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
                'Accept': 'application/json',
            },
            credentials: 'same-origin',
            body: JSON.stringify({ rows: collected.payloadRows }),
        })
            .then(function (response) {
                return response.json().then(function (data) {
                    return { ok: response.ok, data: data };
                });
            })
            .then(function (result) {
                saveSpinner.classList.add('d-none');
                if (!result.ok || result.data.ok === false) {
                    (result.data.errors || []).forEach(function (err) {
                        var mapped = collected.indexMap[err.index];
                        if (mapped && mapped.domRow) {
                            setRowError(mapped.domRow, err.message);
                        }
                    });
                    saveBtn.disabled = false;
                    updateSaveCount();
                    return;
                }
                var created = result.data.created || [];
                var skipped = result.data.skipped || [];
                if (window.notify) {
                    window.notify('success', created.length + ' reminder(s) set');
                    if (skipped.length) {
                        window.notify('info', skipped.length + ' already existed');
                    }
                }
                bootstrap.Modal.getOrCreateInstance(setModalEl).hide();
                if (typeof window.patchReminderFooterPill === 'function') {
                    window.patchReminderFooterPill();
                }
                document.dispatchEvent(new CustomEvent('reminders:changed', {
                    detail: { contractId: activeContractId || pageContractId },
                }));
            })
            .catch(function () {
                saveSpinner.classList.add('d-none');
                saveBtn.disabled = false;
                if (window.notify) {
                    window.notify('error', 'Could not save reminders.');
                }
            });
    }

    function openSetRemindersModal(contractId) {
        var id = contractId || pageContractId;
        loadPresets(id, defaultContractNumber);
    }

    function promptAfterToggle(contractId) {
        pendingToggleContractId = contractId || pageContractId;
        bootstrap.Modal.getOrCreateInstance(promptModalEl).show();
    }

    if (promptConfirmBtn) {
        promptConfirmBtn.addEventListener('click', function () {
            bootstrap.Modal.getOrCreateInstance(promptModalEl).hide();
            openSetRemindersModal(pendingToggleContractId);
        });
    }

    if (addRowBtn) {
        addRowBtn.addEventListener('click', appendCustomRow);
    }

    if (saveBtn) {
        saveBtn.addEventListener('click', saveReminders);
    }

    document.addEventListener('click', function (event) {
        var trigger = event.target.closest('[data-action="open-set-reminders"]');
        if (!trigger) {
            return;
        }
        var cid = parseInt(trigger.dataset.contractId, 10) || pageContractId;
        openSetRemindersModal(cid);
    });

    window.SetReminders = {
        open: openSetRemindersModal,
        promptAfterToggle: promptAfterToggle,
    };
})();
