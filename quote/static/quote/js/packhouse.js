/*
 * Packhouse quote requests (Phase 2).
 *
 *   QuotePackhouse.initDrawer(form, ctx)  -- the "Packhouse quotes for this SOL" panel inside
 *       the quote drawer's Packaging section: list what was asked, ask more packhouses
 *       (pick -> preview -> send), and "Use" a recorded price.
 *   QuotePackhouse.initReplies(root, ctx) -- the banner in the message pane where the rep types
 *       in the price a packhouse answered with.
 *
 * Composing, sending and pricing are server-side (services/packhouse.py); this only renders
 * the preview it returns and posts the same fields back. Loaded by mailbox/inbox.html.
 *
 * ctx (from inbox.html): root, post(url, FormData) -> Promise({ok, body}), esc, debounce,
 *   searchUrl, toast(kind, text), solNumber(), solData(), lineId() (null when Combined),
 *   applyQuote(request).
 */
(function () {
  'use strict';

  function trimNumber(value) {
    const n = parseFloat(value);
    return Number.isFinite(n) ? String(n) : '';
  }
  function money(value, dp) {
    const n = parseFloat(value);
    return Number.isFinite(n) ? '$' + n.toFixed(dp) : '';
  }
  // Unit prices carry up to 5 decimals; show them without padding zeros but never under 2.
  function unitMoney(value) {
    const n = parseFloat(value);
    if (!Number.isFinite(n)) return '';
    let s = n.toFixed(5).replace(/0+$/, '');
    const dp = s.length - s.indexOf('.') - 1;
    if (dp < 2) s += '0'.repeat(2 - dp);
    return '$' + s;
  }
  function mailboxLink(emailId) {
    return window.location.pathname + '?email=' + encodeURIComponent(emailId);
  }

  function initDrawer(form, ctx) {
    const $ = sel => form.querySelector(sel);
    const esc = ctx.esc;
    const chosen = new Map();   // packhouse id -> name
    let previewing = false;

    function requests() { return (ctx.solData() || {}).packhouse_requests || []; }
    function history() { return (ctx.solData() || {}).packhouse_history || []; }
    function urlFor(attr) { return ctx.root.dataset[attr].replace('_SOL_', encodeURIComponent(ctx.solNumber())); }

    // ── What has been asked already ───────────────────────────────────────
    function renderRequests() {
      const rows = requests();
      $('#qPhRequests').innerHTML = rows.length ? rows.map(r => {
        const replied = r.status === 'RESPONDED';
        let detail;
        if (r.unit) {
          detail = '<div class="small">' + esc(unitMoney(r.unit)) + ' / unit' +
            (r.total ? ' &middot; ' + esc(money(r.total, 2)) + ' for ' + esc(r.quantity) : '') +
            (r.lead_days ? ' &middot; ' + esc(r.lead_days) + ' days' : '') + '</div>' +
            (r.notes ? '<div class="small text-body-secondary">' + esc(r.notes) + '</div>' : '');
        } else if (replied && r.reply_email_id) {
          detail = '<div class="small"><a href="' + esc(mailboxLink(r.reply_email_id)) +
            '">Open their reply</a> and record the price there.</div>';
        } else if (replied) {
          detail = '<div class="small text-body-secondary">Replied. No price recorded yet.</div>';
        } else {
          detail = '<div class="small text-body-secondary">Waiting for a reply.</div>';
        }
        return '<div class="quote-ph-row">' +
          '<div class="d-flex justify-content-between align-items-start gap-2">' +
          '<div><strong>' + esc(r.name) + '</strong> ' +
          '<span class="badge ' + (r.unit ? 'text-bg-success' : replied ? 'text-bg-info' : 'text-bg-light border') + '">' +
          esc(r.unit ? 'Quoted' : r.status_label) + '</span>' +
          '<div class="small text-body-secondary">asked ' + esc(r.sent) + ' &middot; ' + esc(r.scope) + ' &middot; qty ' + esc(r.quantity) + '</div></div>' +
          (r.unit ? '<button type="button" class="btn btn-outline-primary btn-sm" data-ph-use="' + esc(r.id) + '">Use</button>' : '') +
          '</div>' + detail + '</div>';
      }).join('') : '<div class="small text-body-secondary">Nobody asked yet.</div>';
    }

    // ── Who to ask ────────────────────────────────────────────────────────
    function renderChosen() {
      $('#qPhChosen').innerHTML = Array.from(chosen, ([id, name]) =>
        '<span class="quote-sol-chip">' + esc(name) +
        '<button type="button" class="btn-close btn-close-sm" data-ph-remove="' + esc(id) + '" aria-label="Remove ' + esc(name) + '"></button></span>').join('');
      $('#qPhPreviewBtn').disabled = chosen.size === 0;
      $('#qPhHistory').innerHTML = history().filter(h => !chosen.has(String(h.id))).map(h =>
        '<button type="button" class="btn btn-outline-secondary btn-sm py-0" data-ph-add="' + esc(h.id) + '" data-name="' + esc(h.name) +
        '" title="Packed this NSN before">' + esc(h.name) + '</button>').join('');
      invalidatePreview();
    }
    function add(id, name) {
      chosen.set(String(id), name);
      $('#qPhSearch').value = ''; $('#qPhResults').innerHTML = '';
      renderChosen();
    }

    // ── Preview / send ────────────────────────────────────────────────────
    function payload() {
      const fd = new FormData();
      chosen.forEach((_name, id) => fd.append('packhouse_ids', id));
      const line = ctx.lineId();
      if (line) fd.append('line_id', line);
      fd.append('note', $('#qPhNote').value);
      ['weight', 'length', 'width', 'height', 'source_notes'].forEach(k => {
        const el = $('[name="dim_' + k + '"]');
        fd.append('dim_' + k, el ? el.value : '');
      });
      const save = $('#qSaveDims');
      if (save && save.checked && !save.disabled) fd.append('save_dims', 'on');
      return fd;
    }
    function showError(text) {
      $('#qPhError').textContent = text || '';
      $('#qPhError').classList.toggle('d-none', !text);
    }
    function invalidatePreview() {
      if (!previewing) return;
      previewing = false;
      $('#qPhPreview').classList.add('d-none');
      $('#qPhPreview').innerHTML = '';
    }

    function renderPreview(p) {
      previewing = true;
      const blocked = p.packhouses.every(h => h.problem);
      $('#qPhPreview').innerHTML =
        (p.warnings.length ? '<div class="alert alert-warning py-1 px-2 small mb-2"><ul class="mb-0 ps-3">' +
          p.warnings.map(w => '<li>' + esc(w) + '</li>').join('') + '</ul></div>' : '') +
        '<ul class="list-unstyled small mb-2">' + p.packhouses.map(h =>
          '<li><strong>' + esc(h.name) + '</strong> &rarr; ' +
          (h.problem ? '<span class="text-danger">' + esc(h.problem) + '</span>'
            : esc(h.recipients.join(', '))) + '</li>').join('') + '</ul>' +
        '<details class="mb-2"><summary class="small">Message (' + esc(p.subject) + ')</summary>' +
        '<pre class="quote-ph-body small mb-1"></pre>' +
        '<div class="small text-body-secondary">Each packhouse gets its own name in the greeting.' +
        (p.attachments.length ? ' Attached: ' + esc(p.attachments.join(', ')) + '.' : ' No PDF stored for this solicitation; the DIBBS link is in the message.') +
        '</div></details>' +
        '<button type="button" class="btn btn-primary btn-sm" id="qPhSend"' + (blocked ? ' disabled' : '') + '>' +
        '<i class="bi bi-send"></i> Send request</button>';
      $('#qPhPreview').querySelector('.quote-ph-body').textContent = p.body;
      $('#qPhPreview').classList.remove('d-none');
    }

    $('#qPhOpen').addEventListener('click', () => {
      $('#qPhCompose').classList.remove('d-none');
      $('#qPhOpen').classList.add('d-none');
      renderChosen();
      $('#qPhSearch').focus();
    });
    $('#qPhCancel').addEventListener('click', () => {
      chosen.clear(); showError('');
      $('#qPhCompose').classList.add('d-none');
      $('#qPhOpen').classList.remove('d-none');
      renderChosen();
    });
    $('#qPhHistory').addEventListener('click', e => {
      const btn = e.target.closest('[data-ph-add]');
      if (btn) add(btn.dataset.phAdd, btn.dataset.name);
    });
    $('#qPhChosen').addEventListener('click', e => {
      const btn = e.target.closest('[data-ph-remove]');
      if (btn) { chosen.delete(btn.dataset.phRemove); renderChosen(); }
    });

    // Enter in the search box must not submit the whole quote form.
    $('#qPhSearch').addEventListener('keydown', e => { if (e.key === 'Enter') e.preventDefault(); });
    $('#qPhSearch').addEventListener('input', ctx.debounce(() => {
      const q = $('#qPhSearch').value.trim();
      if (q.length < 2) { $('#qPhResults').innerHTML = ''; return; }
      fetch(ctx.searchUrl + '?q=' + encodeURIComponent(q)).then(r => r.json()).then(res => {
        const rows = res.results.slice().sort((a, b) => (b.packhouse ? 1 : 0) - (a.packhouse ? 1 : 0));
        $('#qPhResults').innerHTML = rows.length ? rows.map(s =>
          '<button type="button" class="list-group-item list-group-item-action py-1" data-id="' + esc(s.id) + '" data-name="' + esc(s.name) + '">' +
          esc(s.name) + (s.packhouse ? ' <span class="badge text-bg-light border">Packhouse</span>' : '') + '</button>').join('')
          : '<div class="list-group-item small text-body-secondary py-1">No suppliers found.</div>';
      });
    }, 250));
    $('#qPhResults').addEventListener('click', e => {
      const btn = e.target.closest('[data-id]');
      if (btn) add(btn.dataset.id, btn.dataset.name);
    });

    // Anything that changes what would be sent makes an old preview stale.
    $('#qPhNote').addEventListener('input', invalidatePreview);
    form.querySelectorAll('[name^="dim_"]').forEach(el => el.addEventListener('input', invalidatePreview));
    form.querySelectorAll('input[name="mode"]').forEach(el => el.addEventListener('change', invalidatePreview));
    $('#qLine').addEventListener('change', invalidatePreview);

    $('#qPhPreviewBtn').addEventListener('click', () => {
      showError('');
      $('#qPhPreviewBtn').disabled = true;
      ctx.post(urlFor('packhousePreviewUrl'), payload()).then(res => {
        $('#qPhPreviewBtn').disabled = chosen.size === 0;
        if (!res.ok) { showError(res.body.error || 'Could not build the preview.'); return; }
        renderPreview(res.body);
      }).catch(() => {
        $('#qPhPreviewBtn').disabled = chosen.size === 0;
        showError('Could not build the preview. Check your connection and try again.');
      });
    });

    $('#qPhPreview').addEventListener('click', e => {
      const btn = e.target.closest('#qPhSend');
      if (!btn) return;
      btn.disabled = true;
      showError('');
      ctx.post(urlFor('packhouseSendUrl'), payload()).then(res => {
        const body = res.body || {};
        if (Array.isArray(body.requests)) (ctx.solData() || {}).packhouse_requests = body.requests;
        if (!res.ok) {
          btn.disabled = false;
          showError(body.error || body.message || 'Nothing was sent.');
          renderRequests();
          return;
        }
        ctx.toast(body.partial ? 'warning' : 'success', body.message, 7000);
        chosen.clear();
        $('#qPhNote').value = '';
        $('#qPhCompose').classList.add('d-none');
        $('#qPhOpen').classList.remove('d-none');
        previewing = false;
        $('#qPhPreview').classList.add('d-none');
        renderChosen();
        renderRequests();
      }).catch(() => {
        btn.disabled = false;
        showError('Could not send. Check your connection and try again.');
      });
    });

    // ── Use a recorded price ──────────────────────────────────────────────
    $('#qPhRequests').addEventListener('click', e => {
      const btn = e.target.closest('[data-ph-use]');
      if (!btn) return;
      const req = requests().find(r => String(r.id) === btn.dataset.phUse);
      if (req) ctx.applyQuote(req);
    });

    function refresh() {
      chosen.clear(); showError('');
      $('#qPhCompose').classList.add('d-none');
      $('#qPhOpen').classList.remove('d-none');
      renderChosen();
      renderRequests();
    }
    refresh();
    return { refresh: refresh };
  }

  function initReplies(root, ctx) {
    const banner = root.querySelector('#qPhReplies');
    if (!banner) return;
    banner.querySelectorAll('.quote-ph-reply').forEach(f => {
      const errorEl = f.querySelector('[data-role="error"]');
      f.addEventListener('submit', e => {
        e.preventDefault();
        errorEl.classList.add('d-none');
        const fd = new FormData(f);
        fd.append('email_id', root.dataset.email);
        const url = root.dataset.packhouseReplyUrl.replace('/0/', '/' + f.dataset.rfq + '/');
        const btn = f.querySelector('button[type="submit"]');
        btn.disabled = true;
        ctx.post(url, fd).then(res => {
          btn.disabled = false;
          if (!res.ok) {
            errorEl.textContent = res.body.error || 'Could not save.';
            errorEl.classList.remove('d-none');
            return;
          }
          const saved = res.body.request;
          f.querySelector('[name="unit"]').value = trimNumber(saved.unit);
          f.querySelector('[name="total"]').value = saved.total;
          f.querySelector('[data-role="state"]').textContent = 'price recorded';
          ctx.toast('success', res.body.message, 6000);
        }).catch(() => {
          btn.disabled = false;
          errorEl.textContent = 'Could not save. Check your connection and try again.';
          errorEl.classList.remove('d-none');
        });
      });
    });
  }

  window.QuotePackhouse = { initDrawer: initDrawer, initReplies: initReplies };
})();
