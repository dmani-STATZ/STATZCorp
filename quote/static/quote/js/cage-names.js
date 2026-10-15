/* Refresh unnamed CAGE cells from the cache when the user comes back to this tab. */
(function () {
  const root = document.querySelector('[data-cage-names-url]');
  if (!root) return;
  const endpoint = root.dataset.cageNamesUrl;
  const MIN_GAP = 2000;
  let inflight = false;
  let lastStarted = 0;
  let timer = null;

  function pendingCages() {
    const seen = [];
    const have = new Set();
    document.querySelectorAll(
      '.quote-cage-name[data-cage-state="missing"], .quote-cage-name[data-cage-state="error"]'
    ).forEach(el => {
      const cage = (el.dataset.cage || '').trim().toUpperCase();
      if (!/^[A-Z0-9]{5}$/.test(cage) || have.has(cage) || seen.length >= 50) return;
      have.add(cage);
      seen.push(cage);
    });
    return seen;
  }

  function schedule() {
    if (timer !== null) return;
    const wait = Math.max(0, MIN_GAP - (Date.now() - lastStarted));
    timer = setTimeout(() => {
      timer = null;
      refresh();
    }, wait);
  }

  function setTitle(el, name, sourceTitle) {
    if (name && sourceTitle) el.title = name + ' \u2014 ' + sourceTitle;
    else if (name) el.title = name;
    else if (sourceTitle) el.title = sourceTitle;
    else el.removeAttribute('title');
  }

  function syncOurs(el, isOurs) {
    const next = el.nextElementSibling;
    const badge = next && next.classList.contains('quote-ours-badge') ? next : null;
    if (isOurs && !badge) {
      const created = document.createElement('span');
      created.className = 'badge quote-ours-badge ms-1';
      created.textContent = 'Ours';
      el.after(created);
    } else if (!isOurs && badge) {
      badge.remove();
    }
  }

  function applyEntry(el, entry) {
    if (!entry) return;
    const state = entry.state || '';
    const source = entry.source || '';
    const name = entry.name || '';
    if (state === 'ok' || source === 'directory') {
      el.textContent = name;
      el.dataset.cageState = state;
      el.dataset.cageSource = source;
      setTitle(el, name, entry.title || '');
      syncOurs(el, !!entry.is_ours);
      return;
    }
    if (state === 'not_found') {
      el.dataset.cageState = 'not_found';
      if (source) el.dataset.cageSource = source;
      const muted = el.querySelector('.quote-cage-name-muted');
      if (muted && muted.textContent.trim() === '\u2014') muted.textContent = 'Not in SAM';
      syncOurs(el, !!entry.is_ours);
    }
  }

  function refresh() {
    const cages = pendingCages();
    if (!cages.length) return;
    if (inflight || (Date.now() - lastStarted) < MIN_GAP) {
      schedule();
      return;
    }
    lastStarted = Date.now();
    inflight = true;
    const params = new URLSearchParams();
    cages.forEach(cage => params.append('cage', cage));
    const joiner = endpoint.indexOf('?') === -1 ? '?' : '&';
    fetch(endpoint + joiner + params.toString(), {
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
      .then(response => {
        if (!response.ok || response.redirected) return null;
        return response.json();
      })
      .then(data => {
        if (!data || !data.names) return;
        Object.keys(data.names).forEach(cage => {
          if (!/^[A-Z0-9]{5}$/.test(cage)) return;
          document.querySelectorAll('.quote-cage-name[data-cage="' + cage + '"]').forEach(el => {
            applyEntry(el, data.names[cage]);
          });
        });
      })
      .catch(err => { console.debug('cage names refresh failed', err); })
      .finally(() => { inflight = false; });
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') refresh();
  });
  window.addEventListener('focus', () => { refresh(); });
})();
