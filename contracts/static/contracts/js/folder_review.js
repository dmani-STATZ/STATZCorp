(function () {
    'use strict';

    var root = document.getElementById('folder-review-root');
    if (!root) {
        return;
    }

    var configEl = document.getElementById('folder-review-config');
    var config = configEl ? JSON.parse(configEl.textContent || '{}') : {};
    var urls = config.urls || {};
    var counts = config.counts || {};
    var activeTab = config.activeTab || 'pairs';

    var matchModalEl = document.getElementById('folderReviewMatchModal');
    var matchModal = matchModalEl && window.bootstrap ? new bootstrap.Modal(matchModalEl) : null;
    var fixModalEl = document.getElementById('folderReviewFixModal');
    var fixModal = fixModalEl && window.bootstrap ? new bootstrap.Modal(fixModalEl) : null;
    var renameModalEl = document.getElementById('folderReviewRenameModal');
    var renameModal = renameModalEl && window.bootstrap ? new bootstrap.Modal(renameModalEl) : null;
    var moveClosedModalEl = document.getElementById('folderReviewMoveClosedModal');
    var moveClosedModal = moveClosedModalEl && window.bootstrap ? new bootstrap.Modal(moveClosedModalEl) : null;
    var moveDoModalEl = document.getElementById('folderReviewMoveDoModal');
    var moveDoModal = moveDoModalEl && window.bootstrap ? new bootstrap.Modal(moveDoModalEl) : null;
    var mergeModalEl = document.getElementById('folderReviewMergeModal');
    var mergeModal = mergeModalEl && window.bootstrap ? new bootstrap.Modal(mergeModalEl) : null;

    var pendingRename = null;
    var pendingMoveClosedIds = [];
    var pendingMoveDoId = null;
    var pendingMerge = null;

    var matchState = {
        mode: 'folder-to-contract',
        driveItemId: '',
        folderLabel: '',
        contractId: null,
        contractLabel: '',
    };
    var pendingFixIds = [];
    var searchTimer = null;

    function csrfToken() {
        if (window.STATZ_CSRF_TOKEN) {
            return window.STATZ_CSRF_TOKEN;
        }
        var el = document.querySelector('#csrf-form [name=csrfmiddlewaretoken]')
            || document.querySelector('[name=csrfmiddlewaretoken]');
        if (el && el.value) {
            return el.value;
        }
        var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }

    function showAlert(kind, message) {
        var box = document.getElementById('folder-review-alerts');
        if (!box) {
            return;
        }
        var div = document.createElement('div');
        div.className = 'alert alert-' + kind + ' alert-dismissible fade show';
        div.setAttribute('role', 'alert');
        var span = document.createElement('span');
        span.textContent = message;
        div.appendChild(span);
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn-close';
        btn.setAttribute('data-bs-dismiss', 'alert');
        btn.setAttribute('aria-label', 'Close');
        div.appendChild(btn);
        box.appendChild(div);
    }

    function setCount(tabKey, value) {
        counts[tabKey] = value;
        var badge = document.querySelector('[data-count-tab="' + tabKey + '"]');
        if (badge) {
            badge.textContent = String(value);
        }
    }

    function decCount(tabKey) {
        setCount(tabKey, Math.max(0, (counts[tabKey] || 0) - 1));
    }

    function incCount(tabKey) {
        setCount(tabKey, (counts[tabKey] || 0) + 1);
    }

    function postJson(url, body) {
        return fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken(),
            },
            body: JSON.stringify(body),
        }).then(function (resp) {
            return resp.json();
        });
    }

    function setBusy(btn, busy) {
        if (!btn) {
            return;
        }
        btn.disabled = !!busy;
    }

    function removeRow(el) {
        if (!el) {
            return;
        }
        var tr = el.closest('tr');
        if (tr) {
            tr.remove();
            return;
        }
        var card = el.closest('[data-row="duplicate-group"]');
        if (card) {
            card.remove();
        }
    }

    function contentsUrl(driveItemId) {
        return (urls.contentsBase || '').replace('__ID__', encodeURIComponent(driveItemId));
    }

    function handleApiResult(btn, data, onOkRemove) {
        if (data && data.ok) {
            if (typeof onOkRemove === 'function') {
                onOkRemove();
            }
            showAlert('success', data.message || 'Done.');
            if (data.skipped && data.skipped.length) {
                showSkippedList(data.skipped);
            }
        } else {
            showAlert('warning', (data && data.message) || 'Request failed.');
        }
    }

    function showSkippedList(skipped) {
        var box = document.getElementById('folder-review-alerts');
        if (!box) {
            return;
        }
        var div = document.createElement('div');
        div.className = 'alert alert-warning';
        var title = document.createElement('div');
        title.textContent = 'Skipped:';
        div.appendChild(title);
        var ul = document.createElement('ul');
        ul.className = 'mb-0 small';
        skipped.forEach(function (row) {
            var li = document.createElement('li');
            li.textContent = (row.item || '') + ': ' + (row.reason || '');
            ul.appendChild(li);
        });
        div.appendChild(ul);
        box.appendChild(div);
    }

    function contractMgmtUrl(contractId) {
        return '/contracts/' + String(contractId) + '/';
    }

    function linkContract(contractId, driveItemId, action, btn) {
        setBusy(btn, true);
        postJson(urls.link, {
            contract_id: contractId,
            drive_item_id: driveItemId,
            action: action,
        }).then(function (data) {
            handleApiResult(btn, data, function () {
                removeRow(btn);
                if (action === 'link_pair') {
                    decCount('pairs');
                } else if (action === 'link_misnamed') {
                    decCount('misnamed');
                } else if (action === 'manual_match') {
                    decCount(activeTab === 'folderless' ? 'folderless' : 'orphans');
                    decCount(activeTab === 'folderless' ? 'folderless' : 'orphans');
                }
            });
        }).finally(function () {
            setBusy(btn, false);
        });
    }

    function ignoreItem(queue, payload, btn, tabKey) {
        setBusy(btn, true);
        var body = { queue: queue, note: '' };
        if (payload.drive_item_id) {
            body.drive_item_id = payload.drive_item_id;
        }
        if (payload.contract_id) {
            body.contract_id = payload.contract_id;
        }
        postJson(urls.ignore, body).then(function (data) {
            handleApiResult(btn, data, function () {
                removeRow(btn);
                decCount(tabKey);
                incCount('ignored');
            });
        }).finally(function () {
            setBusy(btn, false);
        });
    }

    function runQuickFix(ids, btn) {
        setBusy(btn, true);
        postJson(urls.quickFix, { contract_ids: ids }).then(function (data) {
            handleApiResult(btn, data, function () {
                ids.forEach(function () {
                    decCount('quick_fix');
                });
                document.querySelectorAll('[data-row="quick-fix"]').forEach(function (row) {
                    var cid = parseInt(row.getAttribute('data-contract-id'), 10);
                    if (ids.indexOf(cid) >= 0) {
                        row.remove();
                    }
                });
            });
        }).finally(function () {
            setBusy(btn, false);
        });
    }

    function openMatchModal(mode, payload) {
        matchState.mode = mode;
        matchState.driveItemId = payload.driveItemId || '';
        matchState.folderLabel = payload.folderLabel || '';
        matchState.contractId = payload.contractId || null;
        matchState.contractLabel = payload.contractLabel || '';
        matchState.pendingContract = null;
        matchState.pendingFolder = null;

        document.getElementById('match-step-search').classList.remove('d-none');
        document.getElementById('match-step-confirm').classList.add('d-none');
        document.getElementById('match-search-input').value = '';
        document.getElementById('match-search-results').textContent = '';
        var title = document.getElementById('folderReviewMatchModalLabel');
        if (title) {
            title.textContent = mode === 'folder-to-contract'
                ? 'Match folder to contract'
                : 'Match contract to folder';
        }
        if (matchModal) {
            matchModal.show();
        }
    }

    function renderSearchResults(items) {
        var ul = document.getElementById('match-search-results');
        if (!ul) {
            return;
        }
        while (ul.firstChild) {
            ul.removeChild(ul.firstChild);
        }
        items.forEach(function (item) {
            var li = document.createElement('button');
            li.type = 'button';
            li.className = 'list-group-item list-group-item-action text-start';
            if (matchState.mode === 'folder-to-contract') {
                li.textContent = (item.contract_number || '') + ' · ' + (item.status || '');
                li.addEventListener('click', function () {
                    matchState.pendingContract = item;
                    showConfirmStep();
                });
            } else {
                li.textContent = (item.name || '') + ' — ' + (item.path || '');
                li.addEventListener('click', function () {
                    matchState.pendingFolder = item;
                    showConfirmStep();
                });
            }
            ul.appendChild(li);
        });
    }

    function showConfirmStep() {
        document.getElementById('match-step-search').classList.add('d-none');
        document.getElementById('match-step-confirm').classList.remove('d-none');
        var folderText = matchState.folderLabel;
        var contractText = matchState.contractLabel;
        if (matchState.mode === 'folder-to-contract' && matchState.pendingContract) {
            contractText = (matchState.pendingContract.contract_number || '')
                + ' · ' + (matchState.pendingContract.status || '');
        }
        if (matchState.mode === 'contract-to-folder' && matchState.pendingFolder) {
            folderText = (matchState.pendingFolder.name || '') + '\n' + (matchState.pendingFolder.path || '');
        }
        document.getElementById('match-confirm-folder').textContent = folderText || '—';
        document.getElementById('match-confirm-contract').textContent = contractText || '—';
    }

    function runSearch(q) {
        if (q.length < 3) {
            renderSearchResults([]);
            return;
        }
        var url = matchState.mode === 'folder-to-contract'
            ? urls.searchContracts + '?q=' + encodeURIComponent(q)
            : urls.searchFolders + '?q=' + encodeURIComponent(q);
        fetch(url, { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.results) {
                    renderSearchResults(data.results.slice(0, 20));
                } else {
                    renderSearchResults([]);
                }
            });
    }

    document.getElementById('match-search-input').addEventListener('input', function (e) {
        var q = (e.target.value || '').trim();
        clearTimeout(searchTimer);
        searchTimer = setTimeout(function () {
            runSearch(q);
        }, 300);
    });

    document.getElementById('match-back-btn').addEventListener('click', function () {
        document.getElementById('match-step-search').classList.remove('d-none');
        document.getElementById('match-step-confirm').classList.add('d-none');
    });

    document.getElementById('match-confirm-btn').addEventListener('click', function () {
        var btn = this;
        var contractId;
        var driveId;
        if (matchState.mode === 'folder-to-contract') {
            contractId = matchState.pendingContract && matchState.pendingContract.id;
            driveId = matchState.driveItemId;
        } else {
            contractId = matchState.contractId;
            driveId = matchState.pendingFolder && matchState.pendingFolder.drive_item_id;
        }
        if (!contractId || !driveId) {
            showAlert('warning', 'Select both sides before confirming.');
            return;
        }
        setBusy(btn, true);
        postJson(urls.link, {
            contract_id: contractId,
            drive_item_id: driveId,
            action: 'manual_match',
        }).then(function (data) {
            handleApiResult(btn, data, function () {
                if (matchModal) {
                    matchModal.hide();
                }
            });
        }).finally(function () {
            setBusy(btn, false);
        });
    });

    var searchInputFix = document.getElementById('match-search-input');
    if (searchInputFix) {
        /* bound above */
    }

    if (document.getElementById('folder-review-rename-confirm')) {
        document.getElementById('folder-review-rename-confirm').addEventListener('click', function () {
            var btn = this;
            if (!pendingRename) {
                return;
            }
            setBusy(btn, true);
            postJson(urls.rename, {
                record_type: pendingRename.recordType,
                record_id: pendingRename.recordId,
            }).then(function (data) {
                handleApiResult(btn, data, function () {
                    if (renameModal) {
                        renameModal.hide();
                    }
                    var row = document.querySelector(
                        '[data-row="name-mismatch"][data-record-id="' + pendingRename.recordId + '"]'
                    );
                    if (row) {
                        row.remove();
                    }
                    decCount('name_mismatch');
                });
            }).finally(function () {
                setBusy(btn, false);
            });
        });
    }

    if (document.getElementById('folder-review-move-closed-confirm')) {
        document.getElementById('folder-review-move-closed-confirm').addEventListener('click', function () {
            var btn = this;
            if (!pendingMoveClosedIds.length) {
                return;
            }
            setBusy(btn, true);
            postJson(urls.moveClosed, { contract_ids: pendingMoveClosedIds }).then(function (data) {
                handleApiResult(btn, data, function () {
                    if (moveClosedModal) {
                        moveClosedModal.hide();
                    }
                    pendingMoveClosedIds.forEach(function (cid) {
                        var row = document.querySelector('[data-row="move-closed"][data-contract-id="' + cid + '"]');
                        if (row) {
                            row.remove();
                        }
                        decCount('move_closed');
                    });
                });
            }).finally(function () {
                setBusy(btn, false);
            });
        });
    }

    if (document.getElementById('folder-review-move-do-confirm')) {
        document.getElementById('folder-review-move-do-confirm').addEventListener('click', function () {
            var btn = this;
            if (!pendingMoveDoId) {
                return;
            }
            setBusy(btn, true);
            postJson(urls.moveDo, { contract_id: pendingMoveDoId }).then(function (data) {
                handleApiResult(btn, data, function () {
                    if (moveDoModal) {
                        moveDoModal.hide();
                    }
                    var row = document.querySelector('[data-row="do-mismatch"][data-contract-id="' + pendingMoveDoId + '"]');
                    if (row) {
                        row.remove();
                    }
                    decCount('do_mismatch');
                });
            }).finally(function () {
                setBusy(btn, false);
            });
        });
    }

    if (document.getElementById('folder-review-merge-confirm')) {
        document.getElementById('folder-review-merge-confirm').addEventListener('click', function () {
            var btn = this;
            if (!pendingMerge) {
                return;
            }
            setBusy(btn, true);
            function runMergeLoop() {
                return postJson(urls.merge, {
                    record_type: pendingMerge.recordType,
                    record_id: pendingMerge.recordId,
                }).then(function (data) {
                    if (!data || !data.ok) {
                        showAlert('warning', (data && data.message) || 'Merge failed.');
                        throw new Error('merge failed');
                    }
                    var prog = document.querySelector('[data-progress-for="' + pendingMerge.recordId + '"]');
                    if (prog) {
                        prog.classList.remove('d-none');
                        prog.textContent = 'Moved ' + (data.done ? data.done.length : 0)
                            + ', remaining ' + (data.remaining != null ? data.remaining : 0);
                    }
                    if (data.skipped && data.skipped.length) {
                        showSkippedList(data.skipped);
                    }
                    if (data.remaining > 0) {
                        return runMergeLoop();
                    }
                    if (mergeModal) {
                        mergeModal.hide();
                    }
                    var card = document.querySelector(
                        '[data-row="merge-group"][data-record-id="' + pendingMerge.recordId + '"]'
                    );
                    if (card) {
                        card.remove();
                    }
                    decCount('ready_to_merge');
                    showAlert('success', data.message || 'Merge complete.');
                });
            }
            runMergeLoop().finally(function () {
                setBusy(btn, false);
            });
        });
    }

    document.getElementById('folder-review-fix-confirm').addEventListener('click', function () {
        var btn = this;
        if (fixModal) {
            fixModal.hide();
        }
        runQuickFix(pendingFixIds, btn);
    });

    root.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-action]');
        if (!btn) {
            return;
        }
        var action = btn.getAttribute('data-action');

        if (action === 'link-pair') {
            linkContract(
                parseInt(btn.getAttribute('data-contract-id'), 10),
                btn.getAttribute('data-drive-item-id'),
                'link_pair',
                btn
            );
        } else if (action === 'link-misnamed') {
            linkContract(
                parseInt(btn.getAttribute('data-contract-id'), 10),
                btn.getAttribute('data-drive-item-id'),
                'link_misnamed',
                btn
            );
        } else if (action === 'ignore-pair') {
            ignoreItem('pairs', { drive_item_id: btn.getAttribute('data-drive-item-id') }, btn, 'pairs');
        } else if (action === 'ignore-misnamed') {
            ignoreItem('misnamed', { drive_item_id: btn.getAttribute('data-drive-item-id') }, btn, 'misnamed');
        } else if (action === 'ignore-orphan') {
            ignoreItem('orphans', { drive_item_id: btn.getAttribute('data-drive-item-id') }, btn, 'orphans');
        } else if (action === 'ignore-folderless') {
            ignoreItem('folderless', { contract_id: parseInt(btn.getAttribute('data-contract-id'), 10) }, btn, 'folderless');
        } else if (action === 'match-folder') {
            openMatchModal('folder-to-contract', {
                driveItemId: btn.getAttribute('data-drive-item-id'),
                folderLabel: (btn.getAttribute('data-folder-name') || '') + ' — ' + (btn.getAttribute('data-folder-path') || ''),
            });
        } else if (action === 'match-contract') {
            openMatchModal('contract-to-folder', {
                contractId: parseInt(btn.getAttribute('data-contract-id'), 10),
                contractLabel: btn.getAttribute('data-contract-number') || '',
            });
        } else if (action === 'pick-duplicate') {
            setBusy(btn, true);
            postJson(urls.duplicate, {
                normalized_number: btn.getAttribute('data-normalized'),
                drive_item_id: btn.getAttribute('data-drive-item-id'),
            }).then(function (data) {
                handleApiResult(btn, data, function () {
                    removeRow(btn);
                    decCount('duplicates');
                });
            }).finally(function () {
                setBusy(btn, false);
            });
        } else if (action === 'ignore-duplicate-group') {
            var ids = (btn.getAttribute('data-drive-ids') || '').split(',').filter(Boolean);
            setBusy(btn, true);
            var chain = Promise.resolve();
            ids.forEach(function (did) {
                chain = chain.then(function () {
                    return postJson(urls.ignore, { queue: 'duplicates', drive_item_id: did, note: 'ignore group' });
                });
            });
            chain.then(function () {
                removeRow(btn);
                decCount('duplicates');
                ids.forEach(function () { incCount('ignored'); });
                showAlert('success', 'Group ignored.');
            }).finally(function () {
                setBusy(btn, false);
            });
        } else if (action === 'show-contents') {
            var did = btn.getAttribute('data-drive-item-id');
            var panel = document.querySelector('[data-contents-for="' + did + '"]');
            if (!panel) {
                return;
            }
            if (!panel.classList.contains('d-none')) {
                panel.classList.add('d-none');
                return;
            }
            panel.classList.remove('d-none');
            panel.textContent = 'Loading…';
            fetch(contentsUrl(did), { credentials: 'same-origin' })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    while (panel.firstChild) {
                        panel.removeChild(panel.firstChild);
                    }
                    if (data.error) {
                        panel.textContent = data.error;
                        return;
                    }
                    var head = document.createElement('div');
                    head.textContent = data.folders + ' subfolder(s)' + (data.truncated ? ' (truncated)' : '');
                    panel.appendChild(head);
                    (data.files || []).forEach(function (file) {
                        var line = document.createElement('div');
                        line.textContent = (file.name || '') + ' · ' + (file.modified || '');
                        panel.appendChild(line);
                    });
                });
        } else if (action === 'fix-one') {
            pendingFixIds = [parseInt(btn.getAttribute('data-contract-id'), 10)];
            var msg = document.getElementById('folder-review-fix-message');
            if (msg) {
                msg.textContent = 'Update the saved path for 1 contract?';
            }
            if (fixModal) {
                fixModal.show();
            }
        } else if (action === 'fix-selected' || action === 'fix-page') {
            var ids = [];
            if (action === 'fix-page') {
                document.querySelectorAll('[data-row="quick-fix"]').forEach(function (row) {
                    ids.push(parseInt(row.getAttribute('data-contract-id'), 10));
                });
            } else {
                document.querySelectorAll('.quick-fix-cb:checked').forEach(function (cb) {
                    ids.push(parseInt(cb.value, 10));
                });
            }
            if (!ids.length) {
                showAlert('warning', 'No contracts selected.');
                return;
            }
            pendingFixIds = ids;
            var msgEl = document.getElementById('folder-review-fix-message');
            if (msgEl) {
                msgEl.textContent = 'Update the saved path for ' + ids.length + ' contract(s)?';
            }
            if (fixModal) {
                fixModal.show();
            }
        } else if (action === 'unignore') {
            setBusy(btn, true);
            postJson(urls.unignore, {
                ignore_id: parseInt(btn.getAttribute('data-ignore-id'), 10),
            }).then(function (data) {
                handleApiResult(btn, data, function () {
                    removeRow(btn);
                    decCount('ignored');
                });
            }).finally(function () {
                setBusy(btn, false);
            });
        } else if (action === 'ignore-name-mismatch') {
            ignoreItem('name_mismatch', { drive_item_id: btn.getAttribute('data-drive-item-id') }, btn, 'name_mismatch');
        } else if (action === 'rename-expected') {
            pendingRename = {
                recordType: btn.getAttribute('data-record-type'),
                recordId: parseInt(btn.getAttribute('data-record-id'), 10),
            };
            var current = btn.getAttribute('data-current-name') || '';
            var expected = btn.getAttribute('data-expected-name') || '';
            var kind = btn.getAttribute('data-mismatch-kind') || '';
            var idiqNum = btn.getAttribute('data-idiq-number') || '';
            var msgEl = document.getElementById('folder-review-rename-message');
            var linkEl = document.getElementById('folder-review-rename-contract-link');
            if (msgEl) {
                if (kind === 'kind') {
                    msgEl.textContent = "Rename '" + current + "' to '" + expected
                        + "' because the DB links this contract to IDIQ "
                        + (idiqNum === 'none' ? '(none)' : idiqNum) + '.';
                } else {
                    msgEl.textContent = "Rename '" + current + "' to '" + expected + "'?';
                }
            }
            if (linkEl) {
                while (linkEl.firstChild) {
                    linkEl.removeChild(linkEl.firstChild);
                }
                if (pendingRename.recordType === 'contract') {
                    var a = document.createElement('a');
                    a.href = contractMgmtUrl(pendingRename.recordId);
                    a.target = '_blank';
                    a.rel = 'noopener';
                    a.textContent = 'Open contract in ERP';
                    linkEl.appendChild(a);
                }
            }
            if (renameModal) {
                renameModal.show();
            }
        } else if (action === 'move-closed-selected' || action === 'move-closed-page') {
            var ids = [];
            if (action === 'move-closed-page') {
                document.querySelectorAll('[data-row="move-closed"]').forEach(function (row) {
                    ids.push(parseInt(row.getAttribute('data-contract-id'), 10));
                });
            } else {
                document.querySelectorAll('.move-closed-cb:checked').forEach(function (cb) {
                    ids.push(parseInt(cb.value, 10));
                });
            }
            if (!ids.length) {
                showAlert('warning', 'No contracts selected.');
                return;
            }
            if (ids.length > 50) {
                showAlert('warning', 'Select at most 50 contracts.');
                return;
            }
            pendingMoveClosedIds = ids;
            var lines = [];
            ids.forEach(function (cid) {
                var row = document.querySelector('[data-row="move-closed"][data-contract-id="' + cid + '"]');
                if (row) {
                    lines.push((row.getAttribute('data-old-path') || '') + ' → '
                        + (row.getAttribute('data-new-path') || ''));
                }
            });
            var countEl = document.getElementById('folder-review-move-closed-count');
            if (countEl) {
                countEl.textContent = 'Move ' + ids.length + ' folder(s) to Closed Contracts?';
            }
            var pre = document.getElementById('folder-review-move-closed-lines');
            if (pre) {
                pre.textContent = lines.slice(0, 10).join('\n');
                if (lines.length > 10) {
                    pre.textContent += '\n… and ' + (lines.length - 10) + ' more';
                }
            }
            if (moveClosedModal) {
                moveClosedModal.show();
            }
        } else if (action === 'move-do') {
            pendingMoveDoId = parseInt(btn.getAttribute('data-contract-id'), 10);
            var oldP = btn.getAttribute('data-old-path') || '';
            var parent = btn.getAttribute('data-new-parent') || '';
            var doMsg = document.getElementById('folder-review-move-do-message');
            if (doMsg) {
                doMsg.textContent = oldP + ' → under IDIQ folder for ' + parent;
            }
            if (moveDoModal) {
                moveDoModal.show();
            }
        } else if (action === 'preview-merge') {
            var rt = btn.getAttribute('data-record-type');
            var rid = btn.getAttribute('data-record-id');
            setBusy(btn, true);
            fetch(urls.mergePreview + '?record_type=' + encodeURIComponent(rt)
                + '&record_id=' + encodeURIComponent(rid), { credentials: 'same-origin' })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (!data.ok) {
                        showAlert('warning', data.message || 'Preview failed.');
                        return;
                    }
                    var panel = document.querySelector('[data-preview-for="' + rid + '"]');
                    if (!panel) {
                        return;
                    }
                    panel.classList.remove('d-none');
                    while (panel.firstChild) {
                        panel.removeChild(panel.firstChild);
                    }
                    (data.losers || []).forEach(function (loser) {
                        var head = document.createElement('div');
                        head.textContent = 'From ' + (loser.loser_path || '');
                        panel.appendChild(head);
                        (loser.children || []).forEach(function (child) {
                            var line = document.createElement('div');
                            line.textContent = (child.name || '') + ' → ' + (child.destination_name || '');
                            if (child.conflict) {
                                line.className = 'text-warning';
                            }
                            panel.appendChild(line);
                        });
                    });
                    var mergeBtn = document.createElement('button');
                    mergeBtn.type = 'button';
                    mergeBtn.className = 'btn btn-secondary btn-sm mt-2';
                    mergeBtn.setAttribute('data-action', 'start-merge');
                    mergeBtn.setAttribute('data-record-type', rt);
                    mergeBtn.setAttribute('data-record-id', rid);
                    mergeBtn.textContent = 'Merge…';
                    panel.appendChild(mergeBtn);
                }).finally(function () {
                    setBusy(btn, false);
                });
        } else if (action === 'start-merge') {
            pendingMerge = {
                recordType: btn.getAttribute('data-record-type'),
                recordId: parseInt(btn.getAttribute('data-record-id'), 10),
            };
            if (mergeModal) {
                mergeModal.show();
            }
        }
    });
})();
