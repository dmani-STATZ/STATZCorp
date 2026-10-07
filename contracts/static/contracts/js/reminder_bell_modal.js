/* global bootstrap */
(function () {
    'use strict';

    var BELL_FILL_PATH = 'M8 16a2 2 0 0 0 2-2H6a2 2 0 0 0 2 2zm.256-14c.666.416 1.736.416 2.256 0l.233-2H7.977l.279 2zm3.398-.785-.742-.128C10.278 1.293 9.526 1 8 1s-2.278.293-3.656.887-.743.128-.743 2.63V6c0 .627-.18 2.003-.459 3.742-.277 1.694-.399 2.956-.459 3.742h11.459c-.06-.786-.182-2.048-.459-3.742-.279-1.741-.459-3.115-.459-3.742V2.845z';
    var BELL_OUTLINE_PATH = 'M8 16a2 2 0 0 0 2-2H6a2 2 0 0 0 2 2zM8 1.918l-.797.161A4.002 4.002 0 0 0 4 6c0 .628-.134 2.197-.459 3.742-.16.767-.376 1.566-.663 2.258h9.244c-.287-.692-.502-1.49-.663-2.258C11.134 8.197 11 6.628 11 6a4.002 4.002 0 0 0-3.203-3.92L8 1.917zM14.22 12c.223.447.481.801.78 1H1c.299-.199.557-.553.78-1C2.68 10.2 3 6.88 3 6c0-2.42 1.72-4.44 4.005-4.901a1 1 0 1 1 1.99 0A5.002 5.002 0 0 1 13 6c0 .88.32 4.2 1.22 6z';

    var root = document.getElementById('reminderBellRoot');
    var statusScript = document.getElementById('reminder-status-data');
    if (!root || !statusScript) {
        return;
    }

    var listUrlBase = root.dataset.listUrl;
    var statusUrl = root.dataset.statusUrl;
    var quickCreateUrl = root.dataset.quickCreateUrl;
    var extendUrlTemplate = root.dataset.extendUrlTemplate;
    var completeUrlTemplate = root.dataset.completeUrlTemplate;
    var deleteUrlTemplate = root.dataset.deleteUrlTemplate;
    var pageContractId = parseInt(root.dataset.contractId, 10);

    var modalEl = document.getElementById('reminderBellModal');
    var modalTitle = document.getElementById('reminderBellModalLabel');
    var loadError = document.getElementById('reminderBellLoadError');
    var loadingEl = document.getElementById('reminderBellLoading');
    var listWrap = document.getElementById('reminderBellListWrap');
    var listEl = document.getElementById('reminderBellList');
    var emptyEl = document.getElementById('reminderBellEmpty');
    var addLabel = document.getElementById('reminderBellAddLabel');
    var addDate = document.getElementById('reminderBellAddDate');
    var addTarget = document.getElementById('reminderBellAddTarget');
    var addBtn = document.getElementById('reminderBellAddBtn');
    var addError = document.getElementById('reminderBellAddError');
    var moreBtn = document.getElementById('reminderBellMore');
    var moreText = moreBtn.querySelector('.reminder-bell-more__text');

    var statusMap = { contract: { state: 'none', pending: 0, overdue: 0 }, clins: {} };
    var activeTargetType = 'contract';
    var activeTargetId = pageContractId;
    var activeRollup = false;
    var mutationInFlight = false;
    var targetsCache = [];

    try {
        statusMap = JSON.parse(statusScript.textContent);
    } catch (e) {
        statusMap = { contract: { state: 'none', pending: 0, overdue: 0 }, clins: {} };
    }

    function bellTooltip(state, pending, overdue) {
        pending = pending || 0;
        overdue = overdue || 0;
        if (state === 'none') {
            return 'No reminders — click to add';
        }
        if (state === 'overdue') {
            return overdue + ' overdue of ' + pending + ' reminder(s)';
        }
        return pending + ' reminder(s)';
    }

    function normalizeStatus(statusObj) {
        if (!statusObj) {
            return { state: 'none', pending: 0, overdue: 0 };
        }
        return {
            state: statusObj.state || 'none',
            pending: statusObj.pending || 0,
            overdue: statusObj.overdue || 0,
        };
    }

    function buildBell(targetType, targetId, statusObj) {
        var st = normalizeStatus(statusObj);
        var tooltip = bellTooltip(st.state, st.pending, st.overdue);
        return '<button type="button"' +
            ' class="btn btn-link p-0 reminder-bell reminder-bell--' + st.state + '"' +
            ' data-target-type="' + targetType + '"' +
            ' data-target-id="' + targetId + '"' +
            ' title="' + tooltip.replace(/"/g, '&quot;') + '"' +
            ' aria-label="' + tooltip.replace(/"/g, '&quot;') + '">' +
            '<svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true">' +
            '<path class="reminder-bell__body" d="' + BELL_FILL_PATH + '"/>' +
            '<path class="reminder-bell__outline" d="' + BELL_OUTLINE_PATH + '"/>' +
            '</svg></button>';
    }
    window.buildBell = buildBell;

    function applyStatus(map) {
        statusMap = map;
        window.__reminderBellStatusMap = map;
        document.querySelectorAll('.reminder-bell').forEach(function (btn) {
            var tt = btn.dataset.targetType;
            var tid = btn.dataset.targetId;
            var st;
            if (tt === 'contract') {
                st = normalizeStatus(map.contract);
            } else {
                st = normalizeStatus(map.clins && map.clins[String(tid)]);
            }
            btn.classList.remove('reminder-bell--none', 'reminder-bell--pending', 'reminder-bell--overdue');
            btn.classList.add('reminder-bell--' + st.state);
            var tip = bellTooltip(st.state, st.pending, st.overdue);
            btn.title = tip;
            btn.setAttribute('aria-label', tip);
        });
    }

    function getCsrfToken() {
        if (typeof window.getCookie === 'function') {
            var c = window.getCookie('csrftoken');
            if (c) {
                return c;
            }
        }
        var fromForm = document.querySelector('#csrf-form [name=csrfmiddlewaretoken]');
        if (fromForm && fromForm.value) {
            return fromForm.value;
        }
        var match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? match[1] : '';
    }

    function formatDisplayDate(iso) {
        if (!iso) {
            return '';
        }
        var parts = iso.slice(0, 10).split('-');
        if (parts.length !== 3) {
            return iso;
        }
        var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        return months[parseInt(parts[1], 10) - 1] + ' ' + parseInt(parts[2], 10) + ', ' + parts[0];
    }

    function defaultAddDate() {
        var d = new Date();
        d.setDate(d.getDate() + 7);
        return d.toISOString().slice(0, 10);
    }

    function populateAddTargets(targets, targetType, targetId) {
        addTarget.innerHTML = '';
        targets.forEach(function (t) {
            var opt = document.createElement('option');
            opt.value = t.target_type + ':' + t.target_id;
            opt.textContent = t.target_label;
            if (t.target_type === targetType && String(t.target_id) === String(targetId)) {
                opt.selected = true;
            }
            addTarget.appendChild(opt);
        });
        if (targetType === 'clin') {
            addTarget.disabled = true;
        } else {
            addTarget.disabled = false;
        }
        addBtn.disabled = !targets.length;
    }

    function clearListItems() {
        listEl.querySelectorAll('.list-group-item').forEach(function (el) {
            el.remove();
        });
    }

    // Items whose bottom is cut off by more than 8px count as hidden.
    function hiddenItemsBelow() {
        var viewBottom = listEl.scrollTop + listEl.clientHeight + 8;
        var hidden = [];
        listEl.querySelectorAll('.list-group-item').forEach(function (el) {
            var top = el.offsetTop - listEl.offsetTop;
            if (top + el.offsetHeight > viewBottom) {
                hidden.push(el);
            }
        });
        return hidden;
    }

    function updateMoreIndicator() {
        var n = hiddenItemsBelow().length;
        moreBtn.hidden = n === 0;
        listWrap.classList.toggle('has-more', n > 0);
        moreText.textContent = n ? n + ' more' : '';
    }

    var moreFrame = null;
    listEl.addEventListener('scroll', function () {
        if (moreFrame) {
            return;
        }
        moreFrame = window.requestAnimationFrame(function () {
            moreFrame = null;
            updateMoreIndicator();
        });
    });

    moreBtn.addEventListener('click', function () {
        var first = hiddenItemsBelow()[0];
        if (!first) {
            return;
        }
        listEl.scrollTo({ top: first.offsetTop - listEl.offsetTop, behavior: 'smooth' });
    });

    modalEl.addEventListener('shown.bs.modal', updateMoreIndicator);

    function renderList(items) {
        clearListItems();
        if (!items.length) {
            emptyEl.classList.remove('d-none');
            updateMoreIndicator();
            return;
        }
        emptyEl.classList.add('d-none');
        items.forEach(function (item) {
            var row = document.createElement('div');
            row.className = 'list-group-item';
            row.dataset.reminderId = item.id;

            var top = document.createElement('div');
            top.className = 'd-flex justify-content-between align-items-start gap-2 flex-wrap';

            var left = document.createElement('div');
            var dateLine = document.createElement('div');
            dateLine.className = 'fw-semibold';
            dateLine.textContent = formatDisplayDate(item.reminder_date);
            left.appendChild(dateLine);

            var labelLine = document.createElement('div');
            labelLine.textContent = item.label;
            left.appendChild(labelLine);

            if (activeRollup && item.target_type === 'clin') {
                var badge = document.createElement('span');
                badge.className = 'badge bg-secondary-subtle text-secondary-emphasis ms-1';
                badge.textContent = item.target_label;
                labelLine.appendChild(badge);
            }

            var statusBadges = document.createElement('div');
            statusBadges.className = 'mt-1';
            if (item.is_overdue) {
                var od = document.createElement('span');
                od.className = 'badge bg-danger me-1';
                od.textContent = 'Overdue';
                statusBadges.appendChild(od);
            } else if (item.is_due_today) {
                var dt = document.createElement('span');
                dt.className = 'badge bg-success me-1';
                dt.textContent = 'Due today';
                statusBadges.appendChild(dt);
            }
            left.appendChild(statusBadges);

            if (item.extension_count > 0 && item.original_reminder_date) {
                var ext = document.createElement('div');
                ext.className = 'small text-body-secondary';
                ext.textContent = 'Extended ×' + item.extension_count + ' · originally ' +
                    formatDisplayDate(item.original_reminder_date);
                left.appendChild(ext);
            }

            var userLine = document.createElement('div');
            userLine.className = 'small text-body-secondary';
            userLine.textContent = item.reminder_user || '';
            left.appendChild(userLine);

            top.appendChild(left);

            if (item.can_edit) {
                var actions = document.createElement('div');
                actions.className = 'd-flex flex-wrap gap-1 align-items-center';

                var completeBtn = document.createElement('button');
                completeBtn.type = 'button';
                completeBtn.className = 'btn btn-success btn-sm';
                completeBtn.textContent = 'Complete';
                completeBtn.addEventListener('click', function () {
                    mutateReminder('complete', item.id);
                });
                actions.appendChild(completeBtn);

                var dropWrap = document.createElement('div');
                dropWrap.className = 'dropdown';
                var dropBtn = document.createElement('button');
                dropBtn.type = 'button';
                dropBtn.className = 'btn btn-outline-secondary btn-sm dropdown-toggle';
                dropBtn.setAttribute('data-bs-toggle', 'dropdown');
                dropBtn.textContent = 'Extend';
                var menu = document.createElement('ul');
                menu.className = 'dropdown-menu';
                [{ label: '+3 days', days: 3 }, { label: '+1 week', days: 7 }].forEach(function (opt) {
                    var li = document.createElement('li');
                    var a = document.createElement('button');
                    a.type = 'button';
                    a.className = 'dropdown-item';
                    a.textContent = opt.label;
                    a.addEventListener('click', function () {
                        mutateReminder('extend', item.id, { days: opt.days });
                    });
                    li.appendChild(a);
                    menu.appendChild(li);
                });
                var pickLi = document.createElement('li');
                var pickBtn = document.createElement('button');
                pickBtn.type = 'button';
                pickBtn.className = 'dropdown-item';
                pickBtn.textContent = 'Pick date…';
                pickBtn.addEventListener('click', function () {
                    var pickRow = row.querySelector('.reminder-bell-pick-date');
                    if (pickRow) {
                        pickRow.classList.toggle('d-none');
                        updateMoreIndicator();
                    }
                });
                pickLi.appendChild(pickBtn);
                menu.appendChild(pickLi);
                dropWrap.appendChild(dropBtn);
                dropWrap.appendChild(menu);
                actions.appendChild(dropWrap);
                // Fixed strategy so the menu isn't clipped by the scrolling list.
                new bootstrap.Dropdown(dropBtn, {
                    popperConfig: function (cfg) {
                        cfg.strategy = 'fixed';
                        return cfg;
                    },
                });

                var pickRow = document.createElement('div');
                pickRow.className = 'reminder-bell-pick-date d-none w-100 mt-2';
                var dateIn = document.createElement('input');
                dateIn.type = 'date';
                dateIn.className = 'form-control form-control-sm d-inline-block w-auto me-2';
                dateIn.min = new Date().toISOString().slice(0, 10);
                var applyBtn = document.createElement('button');
                applyBtn.type = 'button';
                applyBtn.className = 'btn btn-primary btn-sm';
                applyBtn.textContent = 'Apply';
                applyBtn.addEventListener('click', function () {
                    if (!dateIn.value) {
                        return;
                    }
                    mutateReminder('extend', item.id, { new_date: dateIn.value });
                });
                pickRow.appendChild(dateIn);
                pickRow.appendChild(applyBtn);
                left.appendChild(pickRow);

                var delBtn = document.createElement('button');
                delBtn.type = 'button';
                delBtn.className = 'btn btn-link btn-sm text-danger';
                delBtn.textContent = 'Delete';
                delBtn.addEventListener('click', function () {
                    if (!window.confirm('Delete this reminder?')) {
                        return;
                    }
                    mutateReminder('delete', item.id);
                });
                actions.appendChild(delBtn);

                top.appendChild(actions);
            }

            row.appendChild(top);
            listEl.appendChild(row);
        });
        updateMoreIndicator();
    }

    function loadList() {
        loadError.classList.add('d-none');
        emptyEl.classList.add('d-none');
        clearListItems();
        updateMoreIndicator();
        loadingEl.classList.remove('d-none');
        var url = listUrlBase + '?target_type=' + encodeURIComponent(activeTargetType) +
            '&target_id=' + encodeURIComponent(activeTargetId);
        return fetch(url, {
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        })
            .then(function (r) {
                if (!r.ok) {
                    throw new Error('load');
                }
                return r.json();
            })
            .then(function (data) {
                if (!data.ok) {
                    throw new Error('load');
                }
                loadingEl.classList.add('d-none');
                modalTitle.textContent = 'Reminders — ' + (data.title_label || '');
                targetsCache = data.targets || [];
                activeRollup = activeTargetType === 'contract';
                populateAddTargets(targetsCache, activeTargetType, activeTargetId);
                renderList(data.items || []);
            })
            .catch(function () {
                loadingEl.classList.add('d-none');
                loadError.classList.remove('d-none');
            });
    }

    function afterMutation() {
        return loadList().then(function () {
            return refreshStatus(true);
        }).then(function () {
            if (typeof window.patchReminderFooterPill === 'function') {
                window.patchReminderFooterPill();
            }
            if (typeof window.refreshCurrentNotesPanel === 'function') {
                window.refreshCurrentNotesPanel();
            } else if (typeof window.fetchContractNotes === 'function') {
                window.fetchContractNotes();
            }
            document.dispatchEvent(new CustomEvent('reminders:changed', {
                detail: { contractId: pageContractId },
            }));
        });
    }

    function mutateReminder(action, reminderId, payload) {
        mutationInFlight = true;
        var url;
        var options = {
            credentials: 'same-origin',
            headers: {
                'X-CSRFToken': getCsrfToken(),
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json',
            },
        };
        if (action === 'complete') {
            url = completeUrlTemplate.replace('/0/', '/' + reminderId + '/');
            options.method = 'POST';
        } else if (action === 'delete') {
            url = deleteUrlTemplate.replace('/0/', '/' + reminderId + '/');
            options.method = 'POST';
        } else if (action === 'extend') {
            url = extendUrlTemplate.replace('/0/', '/' + reminderId + '/');
            options.method = 'POST';
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(payload || {});
        } else {
            mutationInFlight = false;
            return;
        }
        fetch(url, options)
            .then(function (r) {
                return r.json().then(function (data) {
                    return { ok: r.ok, data: data };
                }).catch(function () {
                    return { ok: false, data: {} };
                });
            })
            .then(function (result) {
                if (!result.ok || result.data.ok === false || result.data.success === false) {
                    var msg = (result.data && (result.data.error || result.data.message)) || 'Action failed.';
                    if (window.notify) {
                        window.notify('error', msg);
                    }
                    return;
                }
                return afterMutation();
            })
            .catch(function () {
                if (window.notify) {
                    window.notify('error', 'Action failed.');
                }
            })
            .finally(function () {
                mutationInFlight = false;
            });
    }

    function refreshStatus(skipDispatch) {
        return fetch(statusUrl, {
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json' },
        })
            .then(function (r) {
                return r.json();
            })
            .then(function (data) {
                if (!data.ok) {
                    return;
                }
                var map = { contract: data.contract, clins: data.clins || {} };
                applyStatus(map);
                if (!skipDispatch) {
                    document.dispatchEvent(new CustomEvent('reminders:changed', {
                        detail: { contractId: pageContractId },
                    }));
                }
            });
    }

    function openBellModal(targetType, targetId) {
        activeTargetType = targetType;
        activeTargetId = parseInt(targetId, 10);
        addLabel.value = '';
        addLabel.classList.remove('is-invalid');
        addDate.value = defaultAddDate();
        addDate.classList.remove('is-invalid');
        addError.classList.add('d-none');
        // Targets come from the list response; block Add until it lands.
        addTarget.innerHTML = '';
        addBtn.disabled = true;
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
        loadList();
    }

    addBtn.addEventListener('click', function () {
        var label = addLabel.value.trim();
        var valid = true;
        if (!label) {
            addLabel.classList.add('is-invalid');
            valid = false;
        } else {
            addLabel.classList.remove('is-invalid');
        }
        if (!addDate.value) {
            addDate.classList.add('is-invalid');
            valid = false;
        } else {
            addDate.classList.remove('is-invalid');
        }
        addError.classList.toggle('d-none', valid);
        if (!valid) {
            return;
        }
        var targetParts = addTarget.value.split(':');
        mutationInFlight = true;
        fetch(quickCreateUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
                'Accept': 'application/json',
            },
            body: JSON.stringify({
                contract_id: pageContractId,
                target_type: targetParts[0],
                target_id: parseInt(targetParts[1], 10),
                label: label,
                reminder_date: addDate.value,
            }),
        })
            .then(function (r) {
                return r.json().then(function (data) {
                    return { ok: r.ok, data: data };
                });
            })
            .then(function (result) {
                if (!result.ok || !result.data.ok) {
                    if (window.notify) {
                        window.notify('error', (result.data && result.data.error) || 'Could not add reminder.');
                    }
                    return;
                }
                addLabel.value = '';
                addDate.value = defaultAddDate();
                return afterMutation();
            })
            .catch(function () {
                if (window.notify) {
                    window.notify('error', 'Could not add reminder.');
                }
            })
            .finally(function () {
                mutationInFlight = false;
            });
    });

    // Capture phase + stopPropagation so bell clicks never reach parent
    // handlers (CLIN row select, links). Don't convert to bubble phase.
    document.addEventListener('click', function (event) {
        var bell = event.target.closest('.reminder-bell');
        if (!bell) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
        window.ReminderBell.open(bell.dataset.targetType, bell.dataset.targetId);
    }, true);

    document.addEventListener('reminders:changed', function () {
        if (mutationInFlight) {
            return;
        }
        refreshStatus(true);
    });

    applyStatus(statusMap);

    window.ReminderBell = {
        open: openBellModal,
        refreshStatus: function () {
            return refreshStatus(false);
        },
    };
})();
