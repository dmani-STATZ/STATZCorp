/**
 * STATZ Daily Arcade - Nonogram Client
 * Vanilla ES6 - No external dependencies or CDN assets.
 * Grading is server-only — this client never evaluates fills locally.
 */

(function () {
    'use strict';

    let attemptToken = null;
    let attemptId = null;
    let isFinished = false;
    let timerInterval = null;
    let totalActiveSeconds = 0;
    let submitting = false;
    let paintMode = 'fill'; // 'fill' | 'mark'
    let lastPayload = null;
    let cellRefs = [];
    let rowClueRefs = [];
    let colClueRefs = [];
    let hoverRow = -1;
    let hoverCol = -1;

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

    function formatTime(totalSec) {
        const mins = Math.floor(totalSec / 60);
        const secs = totalSec % 60;
        return String(mins).padStart(2, '0') + ':' + String(secs).padStart(2, '0');
    }

    function startTimer(initialActiveMs) {
        totalActiveSeconds = Math.floor((initialActiveMs || 0) / 1000);
        const timerEl = document.getElementById('timer-val');
        if (timerEl) timerEl.textContent = formatTime(totalActiveSeconds);

        if (timerInterval) clearInterval(timerInterval);

        if (!isFinished) {
            timerInterval = setInterval(function () {
                totalActiveSeconds += 1;
                if (timerEl) timerEl.textContent = formatTime(totalActiveSeconds);
            }, 1000);
        }
    }

    function stopTimer() {
        if (timerInterval) {
            clearInterval(timerInterval);
            timerInterval = null;
        }
    }

    function setMessage(text) {
        const el = document.getElementById('ng-message');
        if (!el) return;
        el.textContent = text || '';
    }

    function setMode(mode) {
        paintMode = mode === 'mark' ? 'mark' : 'fill';
        document.querySelectorAll('.ng-mode-btn').forEach(function (btn) {
            const active = btn.dataset.mode === paintMode;
            btn.classList.toggle('active', active);
            if (btn.dataset.mode === 'fill') {
                btn.classList.toggle('btn-dark', active);
                btn.classList.toggle('btn-outline-secondary', !active);
            } else {
                btn.classList.toggle('btn-secondary', active);
                btn.classList.toggle('btn-outline-secondary', !active);
            }
        });
    }

    function cellKey(r, c) {
        return r + ',' + c;
    }

    function buildSets(payload) {
        const filled = {};
        const marked = {};
        (payload.filled || []).forEach(function (pair) {
            filled[cellKey(pair[0], pair[1])] = true;
        });
        (payload.marked || []).forEach(function (pair) {
            marked[cellKey(pair[0], pair[1])] = true;
        });
        return { filled: filled, marked: marked };
    }

    function updateCounters(payload) {
        const freeEl = document.getElementById('free-misses-val');
        const mistEl = document.getElementById('mistakes-val');
        if (freeEl) freeEl.textContent = String(payload.free_misses_left != null ? payload.free_misses_left : 2);
        if (mistEl) mistEl.textContent = String(payload.mistakes != null ? payload.mistakes : 0);
    }

    function clearHover() {
        if (hoverRow >= 0 && cellRefs[hoverRow]) {
            cellRefs[hoverRow].forEach(function (cell) {
                cell.classList.remove('hl');
            });
            if (rowClueRefs[hoverRow]) rowClueRefs[hoverRow].classList.remove('hl');
        }
        if (hoverCol >= 0) {
            cellRefs.forEach(function (row) {
                if (row[hoverCol]) row[hoverCol].classList.remove('hl');
            });
            if (colClueRefs[hoverCol]) colClueRefs[hoverCol].classList.remove('hl');
        }
        hoverRow = -1;
        hoverCol = -1;
    }

    function setHover(r, c) {
        if (r === hoverRow && c === hoverCol) return;
        clearHover();
        hoverRow = r;
        hoverCol = c;
        if (cellRefs[r]) {
            cellRefs[r].forEach(function (cell) {
                cell.classList.add('hl');
            });
        }
        cellRefs.forEach(function (row) {
            if (row[c]) row[c].classList.add('hl');
        });
        if (rowClueRefs[r]) rowClueRefs[r].classList.add('hl');
        if (colClueRefs[c]) colClueRefs[c].classList.add('hl');
    }

    function onCellHover(e) {
        const row = parseInt(e.currentTarget.dataset.row, 10);
        const col = parseInt(e.currentTarget.dataset.col, 10);
        setHover(row, col);
    }

    function renderBoard(payload) {
        const gridEl = document.getElementById('ng-grid');
        if (!gridEl || !payload) return;

        const nrows = payload.nrows || 0;
        const ncols = payload.ncols || 0;
        const rowClues = payload.row_clues || [];
        const colClues = payload.col_clues || [];
        const sets = buildSets(payload);

        // Clue gutters and cells share these tracks, so the two regions cannot drift.
        gridEl.style.gridTemplateColumns = 'max-content repeat(' + ncols + ', var(--ng-cell))';
        gridEl.style.gridTemplateRows = 'max-content repeat(' + nrows + ', var(--ng-cell))';
        gridEl.innerHTML = '';

        hoverRow = -1;
        hoverCol = -1;
        cellRefs = [];
        rowClueRefs = [];
        colClueRefs = [];

        const corner = document.createElement('div');
        corner.className = 'ng-corner';
        gridEl.appendChild(corner);

        for (let c = 0; c < ncols; c++) {
            const clues = document.createElement('div');
            clues.className = 'ng-col-clues';
            const vals = colClues[c] || [0];
            vals.forEach(function (v) {
                const span = document.createElement('span');
                span.textContent = String(v);
                clues.appendChild(span);
            });
            colClueRefs[c] = clues;
            gridEl.appendChild(clues);
        }

        for (let r = 0; r < nrows; r++) {
            const rowClueEl = document.createElement('div');
            rowClueEl.className = 'ng-row-clues';
            const vals = rowClues[r] || [0];
            vals.forEach(function (v) {
                const span = document.createElement('span');
                span.textContent = String(v);
                rowClueEl.appendChild(span);
            });
            rowClueRefs[r] = rowClueEl;
            gridEl.appendChild(rowClueEl);

            cellRefs[r] = [];
            for (let c = 0; c < ncols; c++) {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'ng-cell';
                btn.dataset.row = String(r);
                btn.dataset.col = String(c);
                if (c > 0 && c % 5 === 0) btn.classList.add('rule-left');
                if (r > 0 && r % 5 === 0) btn.classList.add('rule-top');
                const k = cellKey(r, c);
                if (sets.filled[k]) {
                    btn.classList.add('filled');
                } else if (sets.marked[k]) {
                    btn.classList.add('marked');
                } else {
                    btn.classList.add('unknown');
                }
                btn.addEventListener('mouseenter', onCellHover);
                if (!isFinished) {
                    btn.addEventListener('click', onCellClick);
                    btn.addEventListener('contextmenu', onCellContext);
                } else {
                    btn.disabled = true;
                }
                cellRefs[r][c] = btn;
                gridEl.appendChild(btn);
            }
        }

        gridEl.addEventListener('mouseleave', clearHover);
        updateCounters(payload);
    }

    function renderRevealArt(payload) {
        const el = document.getElementById('res-art');
        if (!el || !payload || !payload.grid) return;
        const grid = payload.grid;
        const ncols = (grid[0] && grid[0].length) || 0;
        el.innerHTML = '';
        el.style.display = 'grid';
        el.style.gap = '1px';
        el.style.gridTemplateColumns = 'repeat(' + ncols + ', 10px)';
        grid.forEach(function (row) {
            for (let i = 0; i < row.length; i++) {
                const cell = document.createElement('span');
                cell.style.width = '10px';
                cell.style.height = '10px';
                cell.style.background = row[i] === '#' ? 'var(--bs-body-color)' : 'var(--bs-secondary-bg)';
                el.appendChild(cell);
            }
        });
    }

    function updateStats(data) {
        if (data.handicap) {
            const hBadge = document.getElementById('handicap-badge');
            if (hBadge && data.handicap.display) {
                hBadge.textContent = 'Handicap: ' + data.handicap.display;
            }
        }
    }

    function handleCompletion(data) {
        isFinished = true;
        stopTimer();

        const panel = document.getElementById('completion-panel');
        const scoreEl = document.getElementById('res-score');
        const rankEl = document.getElementById('res-rank');
        const hResEl = document.getElementById('res-handicap');
        const nameEl = document.getElementById('res-name');

        if (nameEl && data.payload && data.payload.name) {
            nameEl.textContent = data.payload.name;
        }
        if (scoreEl) {
            scoreEl.textContent = data.score_display || String(data.score);
        }
        if (rankEl) {
            rankEl.textContent = data.rank ? '#' + data.rank : 'Completed';
        }
        if (hResEl && data.handicap) {
            hResEl.textContent = data.handicap.display || '—';
        }
        renderRevealArt(data.payload);
        if (panel) panel.classList.remove('d-none');
        renderBoard(data.payload);
    }

    function applyServerPayload(payload) {
        lastPayload = payload;
        renderBoard(payload);
    }

    function submitMove(action, row, col) {
        if (isFinished || !attemptToken || !attemptId || submitting) return;

        submitting = true;
        fetch(window.ARCADE_MOVE_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                token: attemptToken,
                attempt_id: attemptId,
                move: { action: action, row: row, col: col }
            })
        })
        .then(function (res) {
            return res.json().then(function (data) {
                return { ok: res.ok, status: res.status, data: data };
            });
        })
        .then(function (result) {
            submitting = false;
            const data = result.data || {};

            if (!result.ok) {
                // Ordinary misclicks — silent.
                if (data.reason === 'already_filled' || data.reason === 'already_marked') {
                    return;
                }
                if (result.status === 409) {
                    setMessage('Puzzle already finished');
                    isFinished = true;
                    return;
                }
                setMessage(data.error || 'Move failed');
                return;
            }

            if (data.status === 'ok') {
                setMessage('');
                updateStats(data);
                applyServerPayload(data.payload);

                if (data.attempt_status === 'solved' || data.attempt_status === 'failed') {
                    handleCompletion(data);
                }
            }
        })
        .catch(function (err) {
            submitting = false;
            console.error('Arcade move error:', err);
            setMessage('Network error');
        });
    }

    function onCellClick(e) {
        e.preventDefault();
        const row = parseInt(e.currentTarget.dataset.row, 10);
        const col = parseInt(e.currentTarget.dataset.col, 10);
        submitMove(paintMode, row, col);
    }

    function onCellContext(e) {
        e.preventDefault();
        const row = parseInt(e.currentTarget.dataset.row, 10);
        const col = parseInt(e.currentTarget.dataset.col, 10);
        submitMove('mark', row, col);
    }

    function initGame() {
        document.getElementById('mode-fill').addEventListener('click', function () {
            setMode('fill');
        });
        document.getElementById('mode-mark').addEventListener('click', function () {
            setMode('mark');
        });
        setMode('fill');

        fetch(window.ARCADE_START_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            }
        })
        .then(function (res) {
            return res.json();
        })
        .then(function (data) {
            if (data.status === 'ok') {
                attemptToken = data.token;
                attemptId = data.attempt_id;
                isFinished = (data.attempt_status !== 'in_progress');

                updateStats(data);
                startTimer(data.active_ms);
                applyServerPayload(data.payload);

                if (isFinished) {
                    handleCompletion(data);
                }
            }
        })
        .catch(function (err) {
            console.error('Arcade start error:', err);
            setMessage('Could not start puzzle');
        });
    }

    document.addEventListener('DOMContentLoaded', initGame);
})();
