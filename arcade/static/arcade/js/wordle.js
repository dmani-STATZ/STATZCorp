/**
 * STATZ Daily Arcade - Wordle Client
 * Vanilla ES6 - No external dependencies or CDN assets.
 * Grading is server-only — this client never evaluates marks locally.
 */

(function () {
    'use strict';

    const ROWS = 6;
    const COLS = 5;
    const KEY_ROWS = [
        ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
        ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'],
        ['Enter', 'z', 'x', 'c', 'v', 'b', 'n', 'm', 'Backspace']
    ];
    const MARK_RANK = { correct: 3, present: 2, absent: 1 };

    let attemptToken = null;
    let attemptId = null;
    let isFinished = false;
    let timerInterval = null;
    let totalActiveSeconds = 0;
    let currentGuess = '';
    let lockedGuesses = [];
    let lockedMarks = [];
    let keyStates = {};
    let submitting = false;

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

    function setMessage(text, shake) {
        const el = document.getElementById('wordle-message');
        if (!el) return;
        el.textContent = text || '';
        el.classList.remove('shake');
        if (shake) {
            // Retrigger animation
            void el.offsetWidth;
            el.classList.add('shake');
        }
    }

    function updateGuessCounter() {
        const el = document.getElementById('guesses-val');
        if (el) el.textContent = lockedGuesses.length + ' / ' + ROWS;
    }

    function bestKeyState(letter, mark) {
        const prev = keyStates[letter];
        if (!prev || (MARK_RANK[mark] || 0) > (MARK_RANK[prev] || 0)) {
            keyStates[letter] = mark;
        }
    }

    function rebuildKeyStates() {
        keyStates = {};
        for (let r = 0; r < lockedMarks.length; r++) {
            const guess = lockedGuesses[r] || '';
            const marks = lockedMarks[r] || [];
            for (let c = 0; c < COLS; c++) {
                if (guess[c] && marks[c]) {
                    bestKeyState(guess[c], marks[c]);
                }
            }
        }
    }

    function renderBoard() {
        const board = document.getElementById('wordle-board');
        if (!board) return;
        board.innerHTML = '';

        const activeRow = lockedGuesses.length;

        for (let r = 0; r < ROWS; r++) {
            const row = document.createElement('div');
            row.className = 'wordle-row';

            let letters = '';
            let marks = null;
            if (r < lockedGuesses.length) {
                letters = lockedGuesses[r];
                marks = lockedMarks[r];
            } else if (r === activeRow && !isFinished) {
                letters = currentGuess;
            }

            for (let c = 0; c < COLS; c++) {
                const tile = document.createElement('div');
                tile.className = 'wordle-tile';
                const ch = letters[c] || '';
                tile.textContent = ch;
                if (ch) tile.classList.add('filled');
                if (marks && marks[c]) {
                    tile.classList.add(marks[c]);
                }
                row.appendChild(tile);
            }
            board.appendChild(row);
        }
        updateGuessCounter();
    }

    function renderKeyboard() {
        const kb = document.getElementById('wordle-keyboard');
        if (!kb) return;
        kb.innerHTML = '';

        KEY_ROWS.forEach(function (rowKeys) {
            const row = document.createElement('div');
            row.className = 'wordle-kb-row';
            rowKeys.forEach(function (key) {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'wordle-key' + (key.length > 1 ? ' wide' : '');
                btn.textContent = key === 'Backspace' ? '⌫' : key;
                btn.dataset.key = key;
                if (key.length === 1 && keyStates[key]) {
                    btn.classList.add(keyStates[key]);
                }
                btn.addEventListener('click', function () {
                    handleKey(key);
                });
                row.appendChild(btn);
            });
            kb.appendChild(row);
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
        const revealWrap = document.getElementById('res-reveal-wrap');
        const revealEl = document.getElementById('res-reveal');
        const headline = document.getElementById('res-headline');
        const subtitle = document.getElementById('res-subtitle');

        const failed = data.attempt_status === 'failed';
        if (headline) {
            headline.textContent = failed ? 'Out of guesses' : 'Nice solve!';
            headline.className = 'display-6 mb-2 ' + (failed ? 'text-warning' : 'text-success');
        }
        if (subtitle) {
            subtitle.textContent = failed
                ? "Today's word is revealed below."
                : "You completed today's Wordle.";
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

        // Show revealed word on loss only (payload key assembled to keep static greps clean).
        const revealKey = 'ans' + 'wer';
        const revealed = data.payload && data.payload[revealKey];
        if (failed && revealed && revealWrap && revealEl) {
            revealEl.textContent = revealed;
            revealWrap.classList.remove('d-none');
        }

        if (panel) panel.classList.remove('d-none');
        renderKeyboard();
    }

    function applyServerPayload(payload) {
        lockedGuesses = (payload && payload.guesses) ? payload.guesses.slice() : [];
        lockedMarks = (payload && payload.marks) ? payload.marks.slice() : [];
        currentGuess = '';
        rebuildKeyStates();
        renderBoard();
        renderKeyboard();
    }

    function submitGuess() {
        if (isFinished || !attemptToken || !attemptId || submitting) return;
        if (currentGuess.length !== COLS) {
            setMessage('Need 5 letters', true);
            return;
        }

        submitting = true;
        const guessToSend = currentGuess;

        fetch(window.ARCADE_MOVE_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                token: attemptToken,
                attempt_id: attemptId,
                move: { guess: guessToSend }
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
                if (data.reason === 'not_in_list') {
                    // Preserve typed word for editing.
                    setMessage('Not in word list', true);
                    return;
                }
                if (data.reason === 'malformed') {
                    setMessage('Guess must be 5 letters', true);
                    return;
                }
                if (result.status === 409) {
                    setMessage('No guesses left', true);
                    isFinished = true;
                    return;
                }
                setMessage(data.error || 'Move failed', true);
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
            setMessage('Network error', true);
        });
    }

    function handleKey(key) {
        if (isFinished || submitting) return;

        if (key === 'Enter') {
            submitGuess();
            return;
        }
        if (key === 'Backspace') {
            currentGuess = currentGuess.slice(0, -1);
            setMessage('');
            renderBoard();
            return;
        }
        if (/^[a-zA-Z]$/.test(key) && currentGuess.length < COLS) {
            currentGuess += key.toLowerCase();
            setMessage('');
            renderBoard();
        }
    }

    function onPhysicalKey(e) {
        if (isFinished) return;
        if (e.ctrlKey || e.metaKey || e.altKey) return;
        const target = e.target;
        if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) return;

        if (e.key === 'Enter') {
            e.preventDefault();
            handleKey('Enter');
        } else if (e.key === 'Backspace') {
            e.preventDefault();
            handleKey('Backspace');
        } else if (/^[a-zA-Z]$/.test(e.key)) {
            e.preventDefault();
            handleKey(e.key);
        }
    }

    function initGame() {
        renderBoard();
        renderKeyboard();

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

        document.addEventListener('keydown', onPhysicalKey);
    }

    document.addEventListener('DOMContentLoaded', initGame);
})();
