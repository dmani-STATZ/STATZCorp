/*
 * The Quotes page (Phase 2): waiting-on-suppliers and logged-quotes tables, the "Enter a quote" picker,
 * close-out / remove actions, and the Log quote tray (the same one the mailbox uses, opened here with no
 * message behind it). Config comes from window.QUOTES_PAGE (see quotes/index.html).
 */
(function () {
  'use strict';
  const CFG = window.QUOTES_PAGE;
  const FLASH_KEY = 'quotesPageFlash';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }
  function post(url, data) {
    const body = data instanceof FormData ? data : new URLSearchParams(data);
    return fetch(url, { method: 'POST', body: body,
      headers: { 'X-CSRFToken': CFG.csrf, 'X-Requested-With': 'XMLHttpRequest' } })
      .then(r => r.json().then(j => ({ ok: r.ok && j.ok !== false, status: r.status, body: j })));
  }
  function debounce(fn, ms) {
    let t = null;
    return function () { const args = arguments; clearTimeout(t); t = setTimeout(() => fn.apply(null, args), ms); };
  }
  function toast(kind, text, ms) { if (window.showToast) window.showToast(kind, text, ms); }

  // A toast that has to outlive the reload that follows an action.
  function flashAndReload(kind, text) {
    try { window.sessionStorage.setItem(FLASH_KEY, JSON.stringify({ kind: kind, text: text })); } catch (e) { /* ignore */ }
    window.location.reload();
  }
  try {
    const flash = window.sessionStorage.getItem(FLASH_KEY);
    if (flash) {
      window.sessionStorage.removeItem(FLASH_KEY);
      const f = JSON.parse(flash);
      setTimeout(() => toast(f.kind, f.text, 6000), 300);
    }
  } catch (e) { /* ignore */ }

  // ── Filter the rows on screen ───────────────────────────────────────────
  const search = document.getElementById('rowSearch');
  if (search) {
    search.addEventListener('input', () => {
      const q = search.value.trim().toLowerCase();
      document.querySelectorAll('tr[data-row]').forEach(tr => tr.classList.toggle('d-none', !!q && !tr.dataset.search.includes(q)));
    });
  }

  // ── The tray ────────────────────────────────────────────────────────────
  const host = document.getElementById('trayHost');
  let tray = null;

  function openTray(sol, supplierId, entry) {
    fetch(CFG.urls.tray + '?sol=' + encodeURIComponent(sol) + '&supplier=' + encodeURIComponent(supplierId),
      { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(r => r.ok ? r.text() : Promise.reject(r.status))
      .then(html => {
        const old = host.querySelector('#quoteDrawer');
        if (old && window.bootstrap) { const inst = bootstrap.Offcanvas.getInstance(old); if (inst) inst.dispose(); }
        host.innerHTML = html;
        const root = host.querySelector('#trayRoot');
        const dataEl = host.querySelector('#quoteDrawerData');
        const phCtx = { root: root, post: post, esc: esc, debounce: debounce, searchUrl: CFG.urls.supplierSearch, toast: toast };
        tray = window.QuoteDrawer.init({
          root: root, container: host, data: dataEl ? JSON.parse(dataEl.textContent) : {},
          post: post, esc: esc, debounce: debounce, searchUrl: CFG.urls.supplierSearch, phCtx: phCtx,
          onSaved: body => flashAndReload('success', body && body.message ? body.message : 'Quote saved.'),
        });
        if (!tray) { toast('error', 'Could not open the quote form.'); return; }
        tray.openQuote(sol, entry || '');
      })
      .catch(() => toast('error', 'Could not open the quote form. Reload the page and try again.'));
  }

  document.addEventListener('click', e => {
    const enter = e.target.closest('[data-enter-quote]');
    if (enter) { openTray(enter.dataset.sol, enter.dataset.supplier, ''); return; }
    const edit = e.target.closest('[data-edit-quote]');
    if (edit) { openTray(edit.dataset.sol, edit.dataset.supplier, edit.dataset.entry); return; }
    const rfq = e.target.closest('[data-rfq-action]');
    if (rfq) { rfqAction(rfq); return; }
    const remove = e.target.closest('[data-remove-quote]');
    if (remove) { askRemove(remove); }
  });

  // ── Waiting list: close a supplier out / bring them back ────────────────
  const declineModalEl = document.getElementById('declineModal');
  let declineFor = null;

  function rfqAction(btn) {
    const action = btn.dataset.rfqAction;
    if (action === 'declined') {
      declineFor = btn;
      document.getElementById('declineWho').textContent = btn.dataset.name + ' on ' + btn.dataset.sol;
      document.getElementById('declineReason').value = '';
      bootstrap.Modal.getOrCreateInstance(declineModalEl).show();
      setTimeout(() => document.getElementById('declineReason').focus(), 300);
      return;
    }
    sendRfqAction(btn, action, '');
  }
  function sendRfqAction(btn, action, reason) {
    post(CFG.urls.rfqClose, { sol: btn.dataset.sol, supplier_id: btn.dataset.supplier, action: action, reason: reason })
      .then(res => {
        if (!res.ok) { toast('error', res.body.error || 'Could not do that.'); return; }
        flashAndReload('success', res.body.message);
      })
      .catch(() => toast('error', 'Could not do that. Check your connection.'));
  }
  document.getElementById('declineConfirm').addEventListener('click', () => {
    if (!declineFor) return;
    bootstrap.Modal.getOrCreateInstance(declineModalEl).hide();
    sendRfqAction(declineFor, 'declined', document.getElementById('declineReason').value);
  });
  document.getElementById('declineReason').addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); document.getElementById('declineConfirm').click(); }
  });

  // ── Logged quotes: remove ───────────────────────────────────────────────
  const removeModalEl = document.getElementById('removeModal');
  let removeFor = null;

  function askRemove(btn) {
    removeFor = btn;
    document.getElementById('removeWho').textContent = btn.dataset.name + "'s quote on " + btn.dataset.sol + ' (' + btn.dataset.covers + ')';
    document.getElementById('removeError').classList.add('d-none');
    bootstrap.Modal.getOrCreateInstance(removeModalEl).show();
  }
  document.getElementById('removeConfirm').addEventListener('click', () => {
    if (!removeFor) return;
    const err = document.getElementById('removeError');
    post(CFG.urls.remove, { sol: removeFor.dataset.sol, supplier_id: removeFor.dataset.supplier, entry: removeFor.dataset.entry })
      .then(res => {
        if (!res.ok) { err.textContent = res.body.error || 'Could not remove it.'; err.classList.remove('d-none'); return; }
        flashAndReload('success', res.body.message);
      })
      .catch(() => { err.textContent = 'Could not remove it. Check your connection.'; err.classList.remove('d-none'); });
  });

  // ── Enter a quote: pick the solicitation, then who quoted ───────────────
  const eqModalEl = document.getElementById('enterQuoteModal');
  const $id = id => document.getElementById(id);
  let eqSol = '';

  function showStep(step) {
    $id('eqStepSol').classList.toggle('d-none', step !== 'sol');
    $id('eqStepSupplier').classList.toggle('d-none', step !== 'supplier');
  }
  function resetPicker() {
    eqSol = '';
    $id('eqSolSearch').value = ''; $id('eqSolResults').innerHTML = '';
    $id('eqSupplierSearch').value = ''; $id('eqSupplierResults').innerHTML = '';
    showStep('sol');
  }
  $id('enterQuoteBtn').addEventListener('click', () => {
    resetPicker();
    bootstrap.Modal.getOrCreateInstance(eqModalEl).show();
    setTimeout(() => $id('eqSolSearch').focus(), 300);
  });
  $id('eqBack').addEventListener('click', () => { resetPicker(); $id('eqSolSearch').focus(); });

  $id('eqSolSearch').addEventListener('input', debounce(() => {
    const q = $id('eqSolSearch').value.trim();
    const out = $id('eqSolResults');
    if (q.length < 3) { out.innerHTML = ''; return; }
    fetch(CFG.urls.solSearch + '?q=' + encodeURIComponent(q)).then(r => r.json()).then(res => {
      out.innerHTML = res.results.length ? res.results.map(s =>
        '<button type="button" class="list-group-item list-group-item-action" data-sol="' + esc(s.sol) + '">' +
        '<span class="font-monospace fw-semibold">' + esc(s.sol) + '</span> ' +
        '<span class="small text-body-secondary">due ' + esc(s.due) + '</span>' +
        '<div class="small">' + esc(s.nsn) + ' ' + esc(s.nomen) + (s.lines > 1 ? ' (+' + (s.lines - 1) + ' lines)' : '') + '</div></button>').join('')
        : '<div class="list-group-item small text-body-secondary">No open solicitation found.</div>';
    });
  }, 250));
  $id('eqSolResults').addEventListener('click', e => {
    const btn = e.target.closest('[data-sol]');
    if (!btn) return;
    eqSol = btn.dataset.sol;
    fetch(CFG.urls.solSuppliers + '?sol=' + encodeURIComponent(eqSol)).then(r => r.json()).then(res => {
      $id('eqSolName').textContent = res.sol;
      $id('eqSolInfo').textContent = (res.item ? res.item + ' · ' : '') + (res.due ? 'due ' + res.due : '');
      const label = { waiting: 'Waiting', quoted: 'Has a quote', closed: 'Closed out' };
      $id('eqRfqSuppliers').innerHTML = res.suppliers.length ? res.suppliers.map(s =>
        '<button type="button" class="list-group-item list-group-item-action d-flex justify-content-between" data-supplier="' + s.id + '">' +
        '<span><span class="fw-semibold">' + esc(s.name) + '</span> <span class="font-monospace small text-body-secondary">' + esc(s.cage) + '</span></span>' +
        '<span class="badge text-bg-light border">' + esc(label[s.state] || s.state) + '</span></button>').join('')
        : '<div class="list-group-item small text-body-secondary">No RFQ has been sent on this solicitation.</div>';
      showStep('supplier');
    });
  });
  function pickSupplier(id) {
    bootstrap.Modal.getOrCreateInstance(eqModalEl).hide();
    openTray(eqSol, id, '');
  }
  $id('eqRfqSuppliers').addEventListener('click', e => {
    const btn = e.target.closest('[data-supplier]');
    if (btn) pickSupplier(btn.dataset.supplier);
  });
  $id('eqSupplierSearch').addEventListener('input', debounce(() => {
    const q = $id('eqSupplierSearch').value.trim();
    const out = $id('eqSupplierResults');
    if (q.length < 2) { out.innerHTML = ''; return; }
    fetch(CFG.urls.supplierSearch + '?q=' + encodeURIComponent(q)).then(r => r.json()).then(res => {
      out.innerHTML = res.results.length ? res.results.map(s =>
        '<button type="button" class="list-group-item list-group-item-action" data-supplier="' + s.id + '">' +
        '<span class="fw-semibold">' + esc(s.name) + '</span> <span class="font-monospace small text-body-secondary">' + esc(s.cage) + '</span></button>').join('')
        : '<div class="list-group-item small text-body-secondary">No suppliers found.</div>';
    });
  }, 250));
  $id('eqSupplierResults').addEventListener('click', e => {
    const btn = e.target.closest('[data-supplier]');
    if (btn) pickSupplier(btn.dataset.supplier);
  });
})();
