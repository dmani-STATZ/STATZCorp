(function () {
    'use strict';

    var COUNTER_FIELDS = [
        ['folders_saved', 'Folders saved'],
        ['graph_calls', 'Graph calls'],
        ['graph_retries', 'Graph retries'],
        ['contract_folders', 'Contract folders'],
        ['delivery_order_folders', 'Delivery order folders'],
        ['other_folders', 'Other folders'],
        ['matched_expected', 'Matched expected'],
        ['matched_elsewhere', 'Matched elsewhere'],
        ['matched_no_db_path', 'Matched no DB path'],
        ['matched_idiq', 'Matched IDIQ'],
        ['no_contract_in_db', 'No contract in DB'],
        ['duplicate_folders', 'Duplicate folders'],
        ['contracts_without_folder', 'Contracts without folder'],
        ['do_parent_mismatch', 'DO parent mismatch'],
        ['drive_ids_written', 'Drive IDs written'],
        ['paths_fixed', 'Paths fixed'],
    ];

    var STATUS_BADGE = {
        running: 'bg-primary',
        completed: 'bg-success',
        failed: 'bg-danger',
        abandoned: 'bg-secondary',
    };

    var LOG_CLASS = {
        INFO: 'text-body',
        WARN: 'text-warning',
        ERROR: 'text-danger',
    };

    var statusBox = document.getElementById('folder-scan-status-box');
    var logBox = document.getElementById('folder-scan-log-box');
    var refreshBtn = document.getElementById('folder-scan-refresh');
    var autoToggle = document.getElementById('folder-scan-auto');
    var lastRefreshed = document.getElementById('last-refreshed-label');
    var jsonUrl = window.location.pathname.replace(/\/?$/, '/status.json');
    var pollTimer = null;
    var userScrolledUp = false;

    if (!statusBox || !logBox) {
        return;
    }

    logBox.addEventListener('scroll', function () {
        var nearBottom = logBox.scrollHeight - logBox.scrollTop - logBox.clientHeight < 40;
        userScrolledUp = !nearBottom;
    });

    function setText(el, text) {
        if (el) {
            el.textContent = text == null ? '' : String(text);
        }
    }

    function badgeClass(status) {
        return STATUS_BADGE[status] || 'bg-secondary';
    }

    function renderStatus(run) {
        if (!run) {
            statusBox.textContent = '';
            var empty = document.createElement('p');
            empty.className = 'text-muted mb-0';
            empty.id = 'scan-empty';
            empty.textContent = "No folder scan runs yet for this company's root path.";
            statusBox.appendChild(empty);
            return;
        }

        statusBox.textContent = '';
        var badge = document.createElement('span');
        badge.id = 'scan-status-badge';
        badge.className = 'badge mb-2 ' + badgeClass(run.status);
        badge.textContent = run.status;
        statusBox.appendChild(badge);

        var dl = document.createElement('dl');
        dl.className = 'row small mb-3';
        var rows = [
            ['Root', run.root_path],
            ['Started', run.started_at],
            ['Finished', run.finished_at || '—'],
            ['Heartbeat', run.heartbeat_at || '—'],
            ['Current path', run.current_path || '—'],
        ];
        rows.forEach(function (pair) {
            var dt = document.createElement('dt');
            dt.className = 'col-sm-3';
            dt.textContent = pair[0];
            var dd = document.createElement('dd');
            dd.className = 'col-sm-9 text-break';
            dd.textContent = pair[1];
            dl.appendChild(dt);
            dl.appendChild(dd);
        });
        statusBox.appendChild(dl);

        var grid = document.createElement('div');
        grid.className = 'row g-2';
        grid.id = 'scan-counters';
        COUNTER_FIELDS.forEach(function (entry) {
            var field = entry[0];
            var label = entry[1];
            var col = document.createElement('div');
            col.className = 'col-6 col-md-4 col-lg-3';
            if (field === 'folders_saved') {
                col.className += ' fs-5 fw-semibold';
            }
            var box = document.createElement('div');
            box.className = 'border rounded p-2 h-100';
            var lbl = document.createElement('div');
            lbl.className = 'text-muted small';
            lbl.textContent = label;
            var val = document.createElement('div');
            val.className = 'scan-counter';
            val.dataset.field = field;
            val.textContent = run[field] != null ? run[field] : 0;
            box.appendChild(lbl);
            box.appendChild(val);
            col.appendChild(box);
            grid.appendChild(col);
        });
        statusBox.appendChild(grid);

        if (run.error_message) {
            var alert = document.createElement('div');
            alert.className = 'alert alert-danger mt-3 mb-0 small';
            alert.id = 'scan-error';
            alert.textContent = run.error_message;
            statusBox.appendChild(alert);
        }
    }

    function renderLogs(logs) {
        logBox.textContent = '';
        (logs || []).forEach(function (row) {
            var line = document.createElement('div');
            line.className = LOG_CLASS[row.level] || 'text-body';
            line.textContent = (row.t ? row.t + ' ' : '') + row.level + ' ' + row.message;
            logBox.appendChild(line);
        });
        if (!userScrolledUp) {
            logBox.scrollTop = logBox.scrollHeight;
        }
    }

    function applyAutoToggle(status) {
        if (!autoToggle) {
            return;
        }
        if (status === 'running') {
            autoToggle.checked = true;
        } else if (status === 'completed' || status === 'failed' || status === 'abandoned') {
            autoToggle.checked = false;
            stopPoll();
        }
    }

    function stopPoll() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    function startPoll() {
        stopPoll();
        if (autoToggle && autoToggle.checked) {
            pollTimer = setInterval(fetchStatus, 3000);
        }
    }

    function fetchStatus() {
        fetch(jsonUrl, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
            .then(function (resp) {
                if (!resp.ok) {
                    throw new Error('HTTP ' + resp.status);
                }
                return resp.json();
            })
            .then(function (data) {
                var run = data.run;
                renderStatus(run);
                renderLogs(run && run.logs ? run.logs : []);
                applyAutoToggle(run ? run.status : '');
                startPoll();
                var now = new Date();
                setText(
                    lastRefreshed,
                    'Last refreshed ' +
                        String(now.getHours()).padStart(2, '0') + ':' +
                        String(now.getMinutes()).padStart(2, '0') + ':' +
                        String(now.getSeconds()).padStart(2, '0')
                );
            })
            .catch(function () {
                stopPoll();
            });
    }

    if (refreshBtn) {
        refreshBtn.addEventListener('click', fetchStatus);
    }
    if (autoToggle) {
        autoToggle.addEventListener('change', startPoll);
    }

    try {
        var initialEl = document.getElementById('folder-scan-initial-data');
        if (initialEl && initialEl.textContent) {
            var initial = JSON.parse(initialEl.textContent);
            renderStatus(initial.run);
            renderLogs(initial.run && initial.run.logs ? initial.run.logs : []);
            applyAutoToggle(initial.run ? initial.run.status : '');
        }
    } catch (e) {
        /* ignore malformed bootstrap JSON */
    }

    fetchStatus();
})();
