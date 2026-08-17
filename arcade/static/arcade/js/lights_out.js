/**
 * STATZ Daily Arcade - Lights Out Client Engine & Interactive Demo
 * Vanilla ES6 - No external dependencies or CDN assets.
 */

(function () {
    'use strict';

    let attemptToken = null;
    let attemptId = null;
    let isFinished = false;
    let timerInterval = null;
    let totalActiveSeconds = 0;

    // --- Interactive 2-Step Demo Engine ---
    let demoStep = 1;
    let demoGrid = [
        [0, 0, 0],
        [0, 1, 0],
        [0, 0, 0]
    ];

    function renderDemoBoard() {
        const boardEl = document.getElementById('demo-board');
        const textEl = document.getElementById('demo-step-text');
        const boxEl = document.getElementById('demo-instruction-box');
        if (!boardEl) return;

        boardEl.innerHTML = '';

        for (let r = 0; r < 3; r++) {
            for (let c = 0; c < 3; c++) {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'demo-cell ' + (demoGrid[r][c] === 1 ? 'cell-on' : 'cell-off');
                if (demoStep <= 2 && r === 1 && c === 1) {
                    btn.classList.add('cell-highlight');
                }
                btn.setAttribute('aria-label', `Demo Row ${r + 1}, Column ${c + 1}`);

                btn.addEventListener('click', function () {
                    handleDemoClick(r, c);
                });

                boardEl.appendChild(btn);
            }
        }

        if (textEl && boxEl) {
            if (demoStep === 1) {
                boxEl.className = 'alert alert-info py-2 px-3 small mb-2';
                textEl.innerHTML = '<strong>Step 1 of 2:</strong> Click the highlighted center light! Notice how it flips itself and its 4 neighbors into a plus shape.';
            } else if (demoStep === 2) {
                boxEl.className = 'alert alert-warning py-2 px-3 small mb-2';
                textEl.innerHTML = '<strong>Step 2 of 2:</strong> Click the center light one more time to toggle the plus shape again and clear all lights!';
            } else {
                boxEl.className = 'alert alert-success py-2 px-3 small mb-2';
                textEl.innerHTML = '🎉 <strong>Awesome!</strong> You cleared all lights. That\'s how Lights Out works! Now try today\'s 5x5 board below.';
            }
        }
    }

    function handleDemoClick(r, c) {
        // Toggle (r, c) and orthogonal neighbors in 3x3 grid
        for (let [dr, dc] of [[0, 0], [-1, 0], [1, 0], [0, -1], [0, 1]]) {
            const nr = r + dr;
            const nc = c + dc;
            if (nr >= 0 && nr < 3 && nc >= 0 && nc < 3) {
                demoGrid[nr][nc] ^= 1;
            }
        }

        const allOff = demoGrid.every(row => row.every(cell => cell === 0));
        if (allOff) {
            demoStep = 3;
        } else if (demoStep === 1) {
            demoStep = 2;
        }

        renderDemoBoard();
    }

    function resetDemo() {
        demoStep = 1;
        demoGrid = [
            [0, 0, 0],
            [0, 1, 0],
            [0, 0, 0]
        ];
        renderDemoBoard();
    }

    function initDemoEngine() {
        const resetBtn = document.getElementById('demo-reset-btn');
        if (resetBtn) {
            resetBtn.addEventListener('click', resetDemo);
        }
        renderDemoBoard();
    }

    // --- Main Game Engine ---
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

    function renderBoard(grid) {
        const boardEl = document.getElementById('lights-out-board');
        if (!boardEl) return;

        boardEl.innerHTML = '';

        for (let r = 0; r < 5; r++) {
            for (let c = 0; c < 5; c++) {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'lo-cell ' + (grid[r][c] === 1 ? 'cell-on' : 'cell-off');
                btn.setAttribute('aria-label', `Row ${r + 1}, Column ${c + 1}`);
                btn.dataset.row = r;
                btn.dataset.col = c;

                if (!isFinished) {
                    btn.addEventListener('click', function () {
                        handleMove(r, c);
                    });
                } else {
                    btn.disabled = true;
                }

                boardEl.appendChild(btn);
            }
        }
    }

    function updateStats(data) {
        const movesEl = document.getElementById('moves-val');
        const parEl = document.getElementById('par-val');

        if (movesEl) movesEl.textContent = data.moves_used !== undefined ? data.moves_used : 0;
        if (parEl && data.par !== undefined) parEl.textContent = data.par;

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
        const overParEl = document.getElementById('res-over-par');
        const rankEl = document.getElementById('res-rank');
        const hResEl = document.getElementById('res-handicap');

        if (overParEl) {
            if (data.score_display) {
                overParEl.textContent = data.score_display;
            } else {
                const op = data.score;
                overParEl.textContent = op > 0 ? `+${op} over par` : op === 0 ? 'Par (0)' : `${op}`;
            }
        }
        if (rankEl) {
            rankEl.textContent = data.rank ? `#${data.rank}` : 'Completed';
        }
        if (hResEl && data.handicap) {
            hResEl.textContent = data.handicap.display || '—';
        }

        if (panel) panel.classList.remove('d-none');
    }

    function handleMove(r, c) {
        if (isFinished || !attemptToken || !attemptId) return;

        fetch(window.ARCADE_MOVE_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                token: attemptToken,
                attempt_id: attemptId,
                move: { row: r, col: c }
            })
        })
        .then(function (res) {
            if (!res.ok) {
                throw new Error('Move failed');
            }
            return res.json();
        })
        .then(function (data) {
            if (data.status === 'ok') {
                updateStats(data);
                renderBoard(data.payload.grid);

                if (data.attempt_status === 'solved') {
                    handleCompletion(data);
                }
            }
        })
        .catch(function (err) {
            console.error('Arcade move error:', err);
        });
    }

    function initGame() {
        initDemoEngine();

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
                renderBoard(data.payload.grid);

                if (isFinished) {
                    handleCompletion(data);
                }
            }
        })
        .catch(function (err) {
            console.error('Arcade start error:', err);
        });
    }

    document.addEventListener('DOMContentLoaded', initGame);
})();
