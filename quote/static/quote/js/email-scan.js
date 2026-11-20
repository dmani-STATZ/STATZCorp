/*
 * The mailbox message pane's "Scan quote" button.
 *
 *   QuoteEmailScan.init(root, { csrf, drawer })
 *
 * Queued Sonnet scans only: POST queues, GET + polling drive the button and status line.
 */
(function () {
  'use strict';

  const POLL_FAST_MS = 5000;
  const POLL_SLOW_MS = 10000;
  const POLL_FAST_CAP_MS = 120000;
  const POLL_GIVE_UP_MS = 900000;
  const ACTIVE_AGE_MAX_S = 600;

  let activeEmail = null;
  let pollTimer = null;
  let pollStartedAt = null;
  let scanCtx = null;
  let lastState = null;

  function readJson(r) {
    if (r.redirected) return Promise.reject(new Error('redirected'));
    return r.json().then(body => ({ status: r.status, ok: r.ok, body: body }));
  }

  function fetchOpts(csrf, method, body) {
    const headers = {
      'X-CSRFToken': csrf || '',
      'X-Requested-With': 'XMLHttpRequest',
    };
    const init = { method: method, headers: headers };
    if (method === 'POST') {
      init.body = body != null ? body : '';
    }
    return init;
  }

  function render(state) {
    if (!scanCtx || !scanCtx.current()) return;
    lastState = state || null;
    const { btn, label, spinner, icon, status } = scanCtx;
    const triage = state && state.triage;
    const active = state && state.active;
    const latest = state && state.latest;

    let btnText = 'Scan quote';
    let enabled = true;
    let showSpinner = false;
    status.textContent = '';

    function setBtn(text, on, spin) {
      btnText = text;
      enabled = on;
      showSpinner = spin;
    }
    function statusLine(text, cls) {
      const row = document.createElement('div');
      if (cls) row.className = cls;
      row.textContent = text;
      status.appendChild(row);
    }

    if (triage && triage.state === 'blocked') {
      setBtn('Blocked sender', false, false);
    } else if (active && active.status === 'queued' && active.age_seconds <= ACTIVE_AGE_MAX_S) {
      setBtn('Scanning…', false, true);
      statusLine('Queued — waiting for the background worker…');
    } else if (active && active.status === 'running' && active.age_seconds <= ACTIVE_AGE_MAX_S) {
      setBtn('Scanning…', false, true);
      statusLine('Scanning…');
    } else if (active && active.stuck) {
      setBtn('Scanning…', false, true);
      statusLine('Still waiting for the background worker. It runs about 5 AM–5 PM Central; after hours the scan waits until morning.');
    } else if (latest && latest.status === 'completed') {
      setBtn('Scan again', true, false);
      let text = 'Scan: found ' + latest.found_count + ' of ' + latest.total_count + ' fields.';
      if (latest.missing && latest.missing.length) {
        text += ' Not found: ' + latest.missing.join(', ') + '.';
      }
      const row = document.createElement('div');
      row.textContent = text;
      if (latest.from_cache) {
        const cached = document.createElement('span');
        cached.className = 'text-body-secondary';
        cached.textContent = ' (cached)';
        row.appendChild(cached);
      }
      status.appendChild(row);
      if (latest.flags && latest.flags.length) {
        statusLine('Check: ' + latest.flags.join(' · '), 'quote-scan-flags');
      }
      if (latest.skipped_attachments && latest.skipped_attachments.length) {
        statusLine(
          'Not read: ' + latest.skipped_attachments.map(a => a.name + ' (' + a.reason + ')').join(', '),
          'text-body-secondary',
        );
      }
    } else if (latest && latest.status === 'failed') {
      setBtn('Scan quote', true, false);
      statusLine(latest.error || 'The scan failed.', 'text-danger');
    }

    label.textContent = btnText;
    btn.disabled = !enabled;
    spinner.classList.toggle('d-none', !showSpinner);
    icon.classList.toggle('d-none', showSpinner);
  }

  function schedulePoll() {
    if (!scanCtx || !scanCtx.current()) return;
    if (pollTimer) clearTimeout(pollTimer);
    if (!pollStartedAt) pollStartedAt = Date.now();
    const elapsed = Date.now() - pollStartedAt;
    if (elapsed >= POLL_GIVE_UP_MS) {
      if (scanCtx.current()) {
        scanCtx.status.textContent = '';
        const row = document.createElement('div');
        row.textContent = 'Still working. Reopen this message later to see the result.';
        scanCtx.status.appendChild(row);
      }
      return;
    }
    const delay = elapsed < POLL_FAST_CAP_MS ? POLL_FAST_MS : POLL_SLOW_MS;
    pollTimer = setTimeout(() => {
      pollTimer = null;
      if (!scanCtx || !scanCtx.current()) return;
      fetch(scanCtx.url, fetchOpts(scanCtx.csrf, 'GET'))
        .then(readJson)
        .then(res => {
          if (!scanCtx.current() || !res.ok) return;
          const state = res.body;
          render(state);
          if (!state.active) {
            if (state.latest && state.latest.status === 'completed'
                && scanCtx.opts.drawer && scanCtx.opts.drawer.applyScan) {
              scanCtx.opts.drawer.applyScan();
            }
            return;
          }
          schedulePoll();
        })
        .catch(() => {});
    }, delay);
  }

  function loadState() {
    if (!scanCtx || !scanCtx.current()) return Promise.resolve();
    return fetch(scanCtx.url, fetchOpts(scanCtx.csrf, 'GET'))
      .then(readJson)
      .then(res => {
        if (!scanCtx.current() || !res.ok) return;
        render(res.body);
        if (res.body.active) schedulePoll();
        else if (pollTimer) {
          clearTimeout(pollTimer);
          pollTimer = null;
          pollStartedAt = null;
        }
      })
      .catch(() => {
        if (scanCtx.current()) {
          scanCtx.status.textContent = '';
          const row = document.createElement('div');
          row.className = 'text-danger';
          row.textContent = 'Could not load the scan status.';
          scanCtx.status.appendChild(row);
        }
      });
  }

  function onClick() {
    if (!scanCtx || !scanCtx.current() || scanCtx.btn.disabled) return;
    scanCtx.btn.disabled = true;
    fetch(scanCtx.url, fetchOpts(scanCtx.csrf, 'POST'))
      .then(readJson)
      .then(res => {
        if (!scanCtx.current()) return;
        const body = res.body || {};
        if (res.status === 202) {
          pollStartedAt = Date.now();
          render(body.state || lastState);
          schedulePoll();
          return;
        }
        if (res.status === 409 || res.status === 503) {
          scanCtx.status.textContent = '';
          const row = document.createElement('div');
          row.className = 'text-danger';
          row.textContent = body.error || 'That scan is not available.';
          scanCtx.status.appendChild(row);
          render(lastState);
          return;
        }
        render(lastState);
      })
      .catch(() => {
        if (!scanCtx.current()) return;
        scanCtx.status.textContent = '';
        const row = document.createElement('div');
        row.className = 'text-danger';
        row.textContent = 'The scan failed. Check your connection and try again.';
        scanCtx.status.appendChild(row);
        render(lastState);
      });
  }

  function init(root, opts) {
    opts = opts || {};
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
    pollStartedAt = null;
    lastState = null;

    const box = root.querySelector('[data-scan-url]');
    if (!box) return null;
    const url = box.dataset.scanUrl;
    const emailId = box.dataset.scanEmail;
    activeEmail = emailId;

    const btn = box.querySelector('[data-scan-button]');
    const label = box.querySelector('[data-scan-label]');
    const spinner = box.querySelector('[data-scan-spinner]');
    const icon = box.querySelector('[data-scan-icon]');
    const status = box.querySelector('[data-scan-status]');

    function current() {
      return activeEmail === emailId && document.body.contains(box);
    }

    scanCtx = { url, csrf: opts.csrf, btn, label, spinner, icon, status, opts, current };
    btn.addEventListener('click', onClick);
    loadState();
    return { reload: () => loadState() };
  }

  window.QuoteEmailScan = { init: init };
})();