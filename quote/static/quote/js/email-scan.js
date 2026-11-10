/*
 * The mailbox message pane's "Scan quote" button.
 *
 *   QuoteEmailScan.init(root, { csrf, drawer })
 *
 * `root` is the message fragment (.quote-msg); the button lives in `[data-scan-url]` (quote:email_scan),
 * rendered only when QUOTE_EMAIL_SCAN_ENABLED is on. The label follows the server's state:
 * Scan quote (normal) -> Deep scan -> Scanned (Deep); a failed scan does not move it on.
 * When a scan finishes, `drawer.applyScan()` refills the Log quote tray (quote-drawer.js decides what
 * may be filled). Answers that arrive after the rep moved to another message are dropped.
 */
(function () {
  'use strict';

  const LABELS = { normal: 'Scan quote', deep: 'Deep scan' };
  const LEVEL_TEXT = { normal: 'Normal scan', deep: 'Deep scan' };
  let activeEmail = null;

  function init(root, opts) {
    opts = opts || {};
    const box = root.querySelector('[data-scan-url]');
    if (!box) return null;
    const url = box.dataset.scanUrl;
    const emailId = box.dataset.scanEmail;
    const btn = box.querySelector('[data-scan-button]');
    const label = box.querySelector('[data-scan-label]');
    const spinner = box.querySelector('[data-scan-spinner]');
    const icon = box.querySelector('[data-scan-icon]');
    const status = box.querySelector('[data-scan-status]');
    let nextLevel = null;
    let busy = false;
    activeEmail = emailId;

    function current() { return activeEmail === emailId && document.body.contains(box); }

    function setButton(level) {
      nextLevel = level || null;
      label.textContent = nextLevel ? LABELS[nextLevel] : 'Scanned (Deep)';
      btn.disabled = busy || !nextLevel;
      btn.title = nextLevel === 'deep' ? 'Read the message again with the stronger model'
        : nextLevel ? 'Read this message and its attachments, then fill the quote tray'
          : 'This message has had a deep scan';
    }
    function setBusy(on) {
      busy = on;
      spinner.classList.toggle('d-none', !on);
      icon.classList.toggle('d-none', on);
      btn.disabled = on || !nextLevel;
    }
    function line(text, cls) {
      const el = document.createElement('div');
      if (cls) el.className = cls;
      el.textContent = text;
      status.appendChild(el);
      return el;
    }
    function showError(text) {
      status.textContent = '';
      line(text, 'text-danger');
    }
    function showSummary(s) {
      status.textContent = '';
      if (!s) return;
      const level = LEVEL_TEXT[s.level] || 'Scan';
      if (s.status === 'failed') { showError(level + ' failed: ' + s.error); return; }
      if (s.status === 'running') { line(level + ' is running…'); return; }
      let text = level + ': found ' + s.found_count + ' of ' + s.total_count + ' fields.';
      if (s.missing && s.missing.length) text += ' Not found: ' + s.missing.join(', ') + '.';
      const first = line(text);
      if (s.from_cache) {
        const cached = document.createElement('span');
        cached.className = 'text-body-secondary';
        cached.textContent = ' (cached)';
        first.appendChild(cached);
      }
      if (s.flags && s.flags.length) line('Check: ' + s.flags.join(' · '), 'quote-scan-flags');
      if (s.skipped_attachments && s.skipped_attachments.length) {
        line('Not read: ' + s.skipped_attachments.map(a => a.name + ' (' + a.reason + ')').join(', '), 'text-body-secondary');
      }
    }

    function readJson(r) {
      if (r.redirected) return Promise.reject(new Error('redirected'));
      return r.json().then(body => ({ status: r.status, ok: r.ok, body: body }));
    }
    function loadState(keepStatus) {
      return fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(readJson)
        .then(res => {
          if (!current() || !res.ok) return;
          setButton(res.body.next_level);
          if (!keepStatus) showSummary(res.body.latest);
        })
        .catch(() => { if (current() && !keepStatus) showError('Could not load the scan status.'); });
    }

    btn.addEventListener('click', () => {
      if (busy || !nextLevel) return;
      setBusy(true);
      status.textContent = '';
      line((LEVEL_TEXT[nextLevel] || 'Scan') + ' running… this can take up to a minute.', 'text-body-secondary');
      fetch(url, {
        method: 'POST',
        body: JSON.stringify({ level: nextLevel }),
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': opts.csrf || '', 'X-Requested-With': 'XMLHttpRequest' },
      })
        .then(readJson)
        .then(res => {
          if (!current()) return;
          setBusy(false);
          const body = res.body || {};
          if (res.status === 409) { showError(body.error || 'That scan is not available.'); loadState(true); return; }
          if (body.status) showSummary(body); else showError(body.error || 'The scan failed.');
          if ('next_level' in body) setButton(body.next_level); else loadState(true);
          if (body.status === 'completed' && opts.drawer && opts.drawer.applyScan) opts.drawer.applyScan();
        })
        .catch(() => {
          if (!current()) return;
          setBusy(false);
          showError('The scan failed. Check your connection and try again.');
        });
    });

    loadState(false);
    return { reload: () => loadState(false) };
  }

  window.QuoteEmailScan = { init: init };
})();
