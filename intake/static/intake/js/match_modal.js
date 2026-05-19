/* Intake matcher modal.
 *
 * Unified driver for buyer/IDIQ/NSN/supplier matching. Pages include the
 * modal partial once and call `IntakeMatch.open({...})` to point it at a
 * specific target_path inside DraftContract.data.
 *
 * Server contract: POST <matchUrl>
 *   {"action": "search", "match_type": ..., "q": ...}      → 200 {results: [...]}
 *   {"action": "apply",  "match_type": ..., "target_path": ..., "record_id": N}
 *                                                          → 200 {ok, data}
 *   {"action": "clear",  "target_path": ...}               → 200 {ok, data}
 *
 * On a successful apply/clear, fires `intake:match-applied` on document with
 * detail = {targetPath, matchType, action, data} so the page can refresh
 * the relevant display.
 */
(function () {
    'use strict';

    const state = {
        matchUrl: null,
        csrfToken: null,
        matchType: null,
        targetPath: null,
    };

    function $(sel, root) {
        return (root || document).querySelector(sel);
    }

    function el() {
        return document.getElementById('intake-match-modal');
    }

    function setStatus(msg, isError) {
        const s = $('#intake-match-status');
        if (!s) return;
        s.textContent = msg || '';
        s.classList.toggle('text-danger', !!isError);
        s.classList.toggle('text-muted', !isError);
    }

    function renderResults(results) {
        const box = $('#intake-match-results');
        box.innerHTML = '';
        if (!results.length) {
            box.innerHTML = '<div class="text-muted small p-2">No matches.</div>';
            return;
        }
        results.forEach(function (r) {
            const item = document.createElement('button');
            item.type = 'button';
            item.className = 'list-group-item list-group-item-action';
            item.innerHTML =
                '<div class="fw-semibold">' + escapeHtml(r.text) + '</div>' +
                (r.subtitle ? '<div class="small text-muted">' + escapeHtml(r.subtitle) + '</div>' : '');
            item.addEventListener('click', function () { applyMatch(r.id); });
            box.appendChild(item);
        });
    }

    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    async function postJSON(body) {
        const resp = await fetch(state.matchUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': state.csrfToken,
            },
            body: JSON.stringify(body),
        });
        const json = await resp.json().catch(function () { return {}; });
        return { ok: resp.ok, status: resp.status, json: json };
    }

    async function runSearch() {
        const q = $('#intake-match-q').value.trim();
        if (q.length < 3) {
            setStatus('Type at least 3 characters.', true);
            return;
        }
        setStatus('Searching...');
        const { ok, json } = await postJSON({
            action: 'search', match_type: state.matchType, q: q,
        });
        if (!ok) {
            setStatus(json.error || 'Search failed.', true);
            return;
        }
        setStatus((json.results || []).length + ' result(s).');
        renderResults(json.results || []);
    }

    async function applyMatch(recordId) {
        setStatus('Applying...');
        const { ok, json } = await postJSON({
            action: 'apply',
            match_type: state.matchType,
            target_path: state.targetPath,
            record_id: recordId,
        });
        if (!ok) {
            setStatus(json.error || 'Apply failed.', true);
            return;
        }
        document.dispatchEvent(new CustomEvent('intake:match-applied', {
            detail: {
                targetPath: state.targetPath,
                matchType: state.matchType,
                action: 'apply',
                data: json.data,
            },
        }));
        close();
    }

    async function clearMatch() {
        setStatus('Clearing...');
        const { ok, json } = await postJSON({
            action: 'clear', target_path: state.targetPath,
        });
        if (!ok) {
            setStatus(json.error || 'Clear failed.', true);
            return;
        }
        document.dispatchEvent(new CustomEvent('intake:match-applied', {
            detail: {
                targetPath: state.targetPath,
                matchType: state.matchType,
                action: 'clear',
                data: json.data,
            },
        }));
        close();
    }

    function open(opts) {
        state.matchType = opts.matchType;
        state.targetPath = opts.targetPath;
        $('#intake-match-title').textContent = opts.title || opts.matchType;
        $('#intake-match-original').textContent = opts.originalText || '(none)';
        $('#intake-match-q').value = opts.originalText || '';
        $('#intake-match-results').innerHTML = '';
        setStatus('');
        el().classList.remove('d-none');
        setTimeout(function () { $('#intake-match-q').focus(); }, 50);
        if ((opts.originalText || '').length >= 3) {
            runSearch();
        }
    }

    function close() {
        el().classList.add('d-none');
    }

    function init(opts) {
        state.matchUrl = opts.matchUrl;
        state.csrfToken = opts.csrfToken;

        document.addEventListener('click', function (ev) {
            const closer = ev.target.closest('[data-match-close]');
            if (closer && el().contains(closer)) { close(); return; }
            const searcher = ev.target.closest('[data-match-search]');
            if (searcher && el().contains(searcher)) { runSearch(); return; }
            const clearer = ev.target.closest('[data-match-clear]');
            if (clearer && el().contains(clearer)) { clearMatch(); return; }
            const opener = ev.target.closest('[data-match-open]');
            if (opener) {
                ev.preventDefault();
                open({
                    matchType: opener.dataset.matchType,
                    targetPath: opener.dataset.targetPath,
                    title: opener.dataset.matchTitle || opener.dataset.matchType,
                    originalText: opener.dataset.matchOriginal || '',
                });
            }
        });
        $('#intake-match-q').addEventListener('keydown', function (ev) {
            if (ev.key === 'Enter') { ev.preventDefault(); runSearch(); }
        });
    }

    window.IntakeMatch = { init: init, open: open, close: close };
})();
