/*
 * The Log quote tray: the slide-out form that records, and edits, a supplier's quote on a solicitation.
 *
 *   QuoteDrawer.init(cfg) -> { form, openQuote(sol, entry), show(), hide() } | null
 *
 * Used by the Mailbox (a message's tray, opened by "Log supplier quote") and by the Quotes page (a tray
 * opened for a chosen solicitation and supplier, no message behind it). Everything about the form lives
 * here: per-SOL / per-quote drafts, saved quotes reopened for editing, quantity-aware unit <-> total
 * fields, the price preview, and the save.
 *
 * cfg: root      element carrying data-save-url, data-draft-owner, data-draft-scope | data-email,
 *                and the packhouse URLs
 *      container element holding #quoteForm and #quoteDrawer
 *      data      the tray payload (services/drawer.drawer_payload)
 *      post(url, FormData|object) -> Promise({ok, body}),  esc(),  debounce()
 *      searchUrl supplier search endpoint
 *      phCtx     shared context for the packhouse panel (see packhouse.js)
 *      onSaved(body) called after a successful save (the page reloads its list / message)
 */
(function () {
  'use strict';

  // ── Decimal-ish money helpers (display only; the server re-prices) ────────
  function num(v) {
    const n = parseFloat(String(v == null ? '' : v).replace(/[$,]/g, ''));
    return Number.isFinite(n) && n >= 0 ? n : 0;
  }
  function round(n, dp) { const f = Math.pow(10, dp); return Math.round((n + Number.EPSILON) * f) / f; }
  function money(n) { return '$' + n.toFixed(2); }

  function init(cfg) {
    const root = cfg.root, container = cfg.container, data = cfg.data;
    const post = cfg.post, esc = cfg.esc, debounce = cfg.debounce;
    const searchUrl = cfg.searchUrl, phCtx = cfg.phCtx;
    const drawerEl = container.querySelector('#quoteDrawer');

    const form = container.querySelector('#quoteForm');
    if (!form) return null;
    const $ = sel => form.querySelector(sel);
    let markupMode = 'pct';   // 'pct' | 'target'
    let packhousePanel = null;

    // Follows `activeSol`, not the <select>: on a change event the select already shows the new SOL
    // while the form still holds the old one's entries (and must be stashed as such).
    function selectedSol() { return data[activeSol] || { lines: [] }; }
    // One quote per supplier per line: once the supplier has quoted some lines, a *new* quote can only
    // cover the lines it has not quoted yet (quoting a line again is an edit of the saved quote).
    function newScopeLines() {
      const sol = selectedSol();
      if (!(sol.cards || []).length) return sol.lines;
      const open = sol.uncovered || [];
      return sol.lines.filter(l => open.indexOf(l.id) !== -1);
    }
    // The lines being priced: a saved quote keeps the lines it was saved for; a new one follows the
    // Combined / Split choice, within the lines still open to it.
    function selectedLines() {
      const sol = selectedSol();
      const card = (sol.cards || []).find(c => c.entry === activeEntry);
      if (card) return sol.lines.filter(l => card.line_ids.indexOf(l.id) !== -1);
      const scope = newScopeLines();
      if ($('#qModeSplit').checked) return scope.filter(l => String(l.id) === $('#qLine').value);
      return scope;
    }
    function basisQty() { return selectedLines().reduce((sum, l) => sum + (l.qty || 0), 0); }

    // ── One form: a new quote, or one already logged, per SOL ────────────────────────────
    // A message can quote several SOLs, and a SOL can already have a quote logged from this message.
    // The drawer is a single form, so it shows exactly one thing at a time -- "New quote" or one saved
    // quote ("card") for the chosen SOL -- and keeps a draft for each. Switching stashes what was
    // typed for the one being left and loads the other. Drafts are written to localStorage on every
    // edit, so they survive closing the drawer, opening another message, or a reload.
    //  * New quote: cleared when it is saved.
    //  * Saved quote: opens showing the saved numbers; editing and saving updates it in place (never a
    //    second copy). Edits are kept only while they differ from what is saved, and dropped if the
    //    quote was changed on the server since they began. A quote already sent to DIBBS is shown
    //    read-only.
    const DRAFT_TTL_MS = 14 * 24 * 3600 * 1000;
    const draftOwner = root.dataset.draftOwner || '0';
    const TEXT_FIELDS = ['#qPart', '#qCage', '#qCost', '#qLead', '#qMoq', '#qTerms', '#qNotes',
      '#qPackhouse', '#qPackhouseId', '#qPackUnit', '#qPackTotal', '#qFreightUnit', '#qFreightTotal',
      '#qDimW', '#qDimL', '#qDimWd', '#qDimH', '#qDimSource', '#qCustomPct'];
    // Only on the Quotes page, where there is no message to say how the quote arrived.
    const MANUAL_FIELDS = ['#qChannel', '#qReceived', '#qContact'];
    const drafts = {};          // "SOL" or "SOL|entry" -> snapshot
    let activeSol = '';         // the SOL the form currently holds
    let activeEntry = '';       // '' = a new quote, else the saved quote being edited
    let baseline = null;        // a saved quote's untouched state, to tell real edits from none
    let dimsEdited = false;     // rep typed dimensions (else they follow the catalog)
    let dimsFor = '';           // NSN those typed dimensions belong to
    let draftsLocked = false;   // set once a quote is saved: no late write may resurrect a draft

    function activeKey() { return activeEntry ? activeSol + '|' + activeEntry : activeSol; }
    function draftKey(key) { return 'quoteDraft:v1:' + draftOwner + ':' + (root.dataset.draftScope || root.dataset.email) + ':' + key; }
    function storeGet(key) { try { return window.localStorage.getItem(key); } catch (e) { return null; } }
    function storeSet(key, value) { try { window.localStorage.setItem(key, value); } catch (e) { /* private mode / full */ } }
    function storeDrop(key) { try { window.localStorage.removeItem(key); } catch (e) { /* ignore */ } }
    function discardDraft(key) { delete drafts[key]; storeDrop(draftKey(key)); }

    function currentCard() {
      return ((selectedSol().cards) || []).find(c => c.entry === activeEntry) || null;
    }
    function defaultEntry(sol) {
      const cards = (data[sol] && data[sol].cards) || [];
      const pick = cards.find(c => !c.locked) || cards[0];
      return pick ? pick.entry : '';
    }
    // A stale "new quote" (an old draft, or the last line just got quoted) has nothing left to cover:
    // show the saved quote instead.
    function normalizeEntry() {
      const sol = selectedSol();
      const cards = sol.cards || [];
      if (!activeEntry && cards.length && !(sol.uncovered || []).length) activeEntry = defaultEntry(activeSol);
      if (activeEntry && !cards.some(c => c.entry === activeEntry)) activeEntry = defaultEntry(activeSol);
    }

    function loadDrafts() {
      Object.keys(data).forEach(sol => {
        const keys = [sol].concat(((data[sol].cards) || []).map(c => sol + '|' + c.entry));
        keys.forEach(key => {
          const raw = storeGet(draftKey(key));
          if (!raw) return;
          try {
            const s = JSON.parse(raw);
            if (s && s.at && Date.now() - s.at < DRAFT_TTL_MS) drafts[key] = s; else storeDrop(draftKey(key));
          } catch (e) { storeDrop(draftKey(key)); }
        });
      });
    }
    function activePill() { const p = form.querySelector('.quote-tip.active'); return p ? p.dataset.pct : ''; }
    function typedSide(unitSel, totalSel) {
      if ($(totalSel).dataset.derived === '1') return 'unit';
      if ($(unitSel).dataset.derived === '1') return 'total';
      return null;
    }
    function snapshot() {
      const s = { at: Date.now(), f: {} };
      TEXT_FIELDS.forEach(sel => { s.f[sel] = $(sel).value; });
      s.packSource = $('#qPackSource').value;
      s.split = $('#qModeSplit').checked;
      s.line = $('#qLine').value;
      s.typed = { pack: typedSide('#qPackUnit', '#qPackTotal'), freight: typedSide('#qFreightUnit', '#qFreightTotal') };
      s.markupMode = markupMode; s.markup = $('#qMarkup').value; s.pill = activePill();
      s.target = $('#qTarget').value; s.price = $('#qPrice').value;
      s.saveDims = $('#qSaveDims').checked; s.dimsEdited = dimsEdited; s.dimsFor = dimsFor;
      s.manual = {};
      MANUAL_FIELDS.forEach(sel => { const el = $(sel); if (el) s.manual[sel] = el.value; });
      return s;
    }
    function strip(s) { const c = Object.assign({}, s); delete c.at; delete c.rev; return JSON.stringify(c); }
    // A new quote with nothing worth keeping: only the prefilled CAGE, the default markup, catalog dimensions.
    function isBlank(s) {
      const skip = { '#qCage': 1, '#qPackhouseId': 1 };
      const typed = TEXT_FIELDS.some(sel => !skip[sel] && String(s.f[sel] || '').trim() !== '' &&
        !(/^#qDim/.test(sel) && !s.dimsEdited));
      const defaultPill = form.querySelector('.quote-tip').dataset.pct;
      return !typed && !(s.markupMode === 'target' && s.price) &&
        s.packSource === $('#qPackSource').options[0].value && (!s.pill || s.pill === defaultPill);
    }
    function updateSolOptions() {
      form.querySelectorAll('#qSol option').forEach(o => {
        const base = o.dataset.base || (o.dataset.base = o.textContent);
        const hasDraft = Object.keys(drafts).some(k => k === o.value || k.indexOf(o.value + '|') === 0);
        o.textContent = base + (hasDraft ? '  • draft' : '') + (o.dataset.logged ? '  ✓ quote logged' : '');
      });
    }
    function draftNote(text) { $('#qDraftNote').textContent = text; }
    function clock() { return new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }); }

    // Keep what is in the form for whatever it currently holds (call before switching away).
    function stash() {
      if (!activeSol || draftsLocked) return;
      const card = currentCard();
      if (card && card.locked) return;
      const key = activeKey();
      const s = snapshot();
      if (card) s.rev = card.rev;
      const unchanged = card ? strip(s) === baseline : isBlank(s);
      if (unchanged) { discardDraft(key); draftNote(''); }
      else { drafts[key] = s; storeSet(draftKey(key), JSON.stringify(s)); draftNote((card ? 'Changes not saved yet · draft kept ' : 'Draft saved ') + clock()); }
      updateSolOptions();
    }
    const stashSoon = debounce(stash, 350);

    function syncPackSource() {
      $('#qPackhouseWrap').classList.toggle('d-none', $('#qPackSource').value !== 'THIRD_PARTY');
    }
    function setPill(pct) {
      form.querySelectorAll('.quote-tip').forEach(p => p.classList.toggle('active', p.dataset.pct === pct));
      $('#qCustomWrap').classList.toggle('d-none', pct !== 'custom');
    }
    // Back to a blank quote for whichever SOL / quote is about to be shown.
    function resetForm() {
      TEXT_FIELDS.forEach(sel => { $(sel).value = ''; });
      $('#qCage').value = $('#qCage').defaultValue;
      ['#qPackUnit', '#qPackTotal', '#qFreightUnit', '#qFreightTotal'].forEach(sel => { $(sel).dataset.derived = ''; });
      $('#qPackSource').value = $('#qPackSource').options[0].value;
      syncPackSource();
      $('#qPackhouseResults').innerHTML = '';
      $('#qModeCombined').checked = true;
      const first = form.querySelector('.quote-tip');
      markupMode = 'pct'; setPill(first.dataset.pct);
      $('#qMarkup').value = first.dataset.pct; $('#qTarget').value = ''; $('#qPrice').value = '';
      $('#qSaveDims').checked = false;
      dimsEdited = false; dimsFor = '';
      $('#qError').classList.add('d-none');
      MANUAL_FIELDS.forEach(sel => {
        const el = $(sel);
        if (!el) return;
        el.value = el.tagName === 'SELECT' ? el.options[0].value : (sel === '#qReceived' ? el.defaultValue : '');
      });
    }
    function applyDraft(s) {
      TEXT_FIELDS.forEach(sel => { if (s.f && sel in s.f) $(sel).value = s.f[sel]; });
      const packOk = Array.from($('#qPackSource').options).some(o => o.value === s.packSource);
      if (packOk) $('#qPackSource').value = s.packSource;
      syncPackSource();
      const sol = selectedSol();
      const lineOk = sol.lines.some(l => String(l.id) === String(s.line));
      if (s.split && lineOk && sol.lines.length > 1) { $('#qModeSplit').checked = true; $('#qLine').value = String(s.line); }
      const t = s.typed || {};
      [['pack', '#qPackUnit', '#qPackTotal'], ['freight', '#qFreightUnit', '#qFreightTotal']].forEach(([k, unitSel, totalSel]) => {
        $(unitSel).dataset.derived = t[k] === 'total' ? '1' : '';
        $(totalSel).dataset.derived = t[k] === 'unit' ? '1' : '';
      });
      markupMode = s.markupMode === 'target' ? 'target' : 'pct';
      if (s.pill) setPill(s.pill);
      $('#qMarkup').value = s.markup || $('#qMarkup').value;
      $('#qTarget').value = markupMode === 'target' ? (s.target || '') : '';
      if (markupMode === 'target') $('#qPrice').value = s.price || '';
      $('#qSaveDims').checked = !!s.saveDims;
      dimsEdited = !!s.dimsEdited; dimsFor = s.dimsFor || '';
      MANUAL_FIELDS.forEach(sel => { const el = $(sel); if (el && s.manual && sel in s.manual) el.value = s.manual[sel]; });
    }
    // Fill the form from a saved quote: what was typed (the side of packaging / freight that was
    // entered, the other follows from the quantity) and how it was marked up.
    function applyCard(card) {
      const f = card.fields;
      const set = (sel, v) => { $(sel).value = v == null ? '' : v; };
      set('#qPart', f.part); set('#qCage', f.cage || $('#qCage').defaultValue);
      set('#qCost', f.cost); set('#qLead', f.lead); set('#qMoq', f.moq); set('#qTerms', f.terms); set('#qNotes', f.notes);
      if (Array.from($('#qPackSource').options).some(o => o.value === f.pack_source)) $('#qPackSource').value = f.pack_source;
      syncPackSource();
      if ($('#qChannel')) {       // how / when / who, on the Quotes page
        if (Array.from($('#qChannel').options).some(o => o.value === f.channel)) $('#qChannel').value = f.channel;
        if (f.received_on) $('#qReceived').value = f.received_on;
        set('#qContact', f.contact);
      }
      set('#qPackhouseId', f.pack_vendor_id); set('#qPackhouse', f.pack_vendor);
      [['pack', '#qPackUnit', '#qPackTotal'], ['freight', '#qFreightUnit', '#qFreightTotal']].forEach(([k, unitSel, totalSel]) => {
        const typed = f[k + '_typed'];
        $(unitSel).dataset.derived = typed === 'total' ? '1' : '';
        $(totalSel).dataset.derived = typed === 'unit' ? '1' : '';
        if (typed === 'unit') set(unitSel, f[k + '_value']);
        if (typed === 'total') set(totalSel, f[k + '_value']);
      });
      if (f.markup_type === 'FIXED') {
        markupMode = 'target'; setPill('custom');
        set('#qTarget', f.markup_value); set('#qPrice', f.markup_value);
      } else {
        markupMode = 'pct';
        const preset = Array.from(form.querySelectorAll('.quote-tip[data-pct]'))
          .find(p => p.dataset.pct !== 'custom' && parseFloat(p.dataset.pct) === parseFloat(f.markup_value));
        if (preset) { setPill(preset.dataset.pct); $('#qMarkup').value = preset.dataset.pct; }
        else { setPill('custom'); set('#qCustomPct', f.markup_value); $('#qMarkup').value = f.markup_value; }
      }
    }
    function cardLabel(c) {
      return (c.locked ? '[sent] ' : '') + c.covers + ' · $' + c.cost + ' cost → $' + c.price + ' · ' + c.days + ' days';
    }
    function lineNumbers(lines) { return lines.map(l => l.line || '?').join(', '); }
    // The quote picker exists to switch between this supplier's quotes on the SOL (when it priced the
    // lines separately) and to add one for lines it has not quoted. With a single quote that covers
    // every line there is nothing to choose, so it stays out of the way (the <select> is still what
    // carries `entry` to the server).
    function fillEntrySelect() {
      const sol = selectedSol();
      const cards = sol.cards || [];
      const open = newScopeLines().length && cards.length;       // lines still open to a new quote
      const canAdd = !cards.length || open;
      $('#qEntryWrap').classList.toggle('d-none', !(cards.length > 1 || (cards.length === 1 && open)));
      $('#qEntry').innerHTML = cards.map(c => '<option value="' + esc(c.entry) + '">' + esc(cardLabel(c)) + '</option>').join('') +
        (canAdd ? '<option value="">' + (cards.length ? '＋ Quote the other line' + (newScopeLines().length > 1 ? 's' : '') +
          ' (' + esc(lineNumbers(newScopeLines())) + ')' : 'New quote') + '</option>' : '');
      $('#qEntry').value = activeEntry;
    }
    // Read-only when the quote has gone to DIBBS; button and helper text follow what is on screen.
    function applyCardState(card) {
      const locked = !!(card && card.locked);
      const sol = selectedSol();
      const cards = sol.cards || [];
      $('#qFields').disabled = locked;
      $('#qLockNote').classList.toggle('d-none', !locked);
      $('#qLockNote span').textContent = locked ? card.lock_reason : '';
      $('#qSave').classList.toggle('d-none', locked);
      $('#qDraftClear').classList.toggle('d-none', locked);
      $('#qSave').textContent = card ? 'Update quote' : 'Save quote to SOL';
      $('#qDraftClear').textContent = card ? 'Undo my changes' : "Clear this SOL's entries";
      $('#qEntryNote').textContent = card
        ? 'Logged ' + card.saved_on + (card.saved_by ? ' by ' + card.saved_by : '') + ' · ' + card.via + ' · ' + card.bid_note
        : (cards.length ? 'A new quote for the line' + (newScopeLines().length > 1 ? 's' : '') + ' this supplier has not quoted yet.' : '');
      $('#qEntryNote').classList.toggle('d-none', !$('#qEntryNote').textContent);
      // Which lines it covers; a saved quote's cannot change, a new one may only take what is still open.
      const note = $('#qScopeNote');
      if (card) {
        note.textContent = 'Covers ' + card.covers.toLowerCase() + ' (qty ' + basisQty() + ').' +
          ((sol.uncovered || []).length ? ' Other lines have no quote from this supplier yet.' : '');
      } else if (cards.length) {
        note.textContent = 'Covers ' + newScopeLines().length + ' line' + (newScopeLines().length === 1 ? '' : 's') +
          ' this supplier has not quoted yet (' + lineNumbers(newScopeLines()) + ').';
      }
      note.classList.toggle('d-none', !card && !cards.length);
    }
    function renderSol() {
      normalizeEntry();
      const sol = selectedSol();
      fillEntrySelect();
      const card = currentCard();
      const scope = newScopeLines();
      $('#qModeWrap').classList.toggle('d-none', scope.length < 2 || !!card);
      $('#qLine').innerHTML = scope.map(l =>
        '<option value="' + l.id + '">Line ' + esc(l.line || '?') + ' — ' + esc(l.nsn) + ' (qty ' + l.qty + ')</option>').join('');
      // The saved quote's untouched state, worked out once by running it through the form.
      if (card && card.base === undefined) {
        resetForm(); applyCard(card); renderLines();
        card.base = strip(snapshot());
      }
      baseline = card ? card.base : null;
      resetForm();
      let draft = drafts[activeKey()];
      if (draft && card && draft.rev !== card.rev) { discardDraft(activeKey()); draft = null; }   // the quote changed since
      if (draft) applyDraft(draft); else if (card) applyCard(card);
      renderLines();
      applyCardState(card);
      draftNote(draft ? (card ? 'Your unsaved changes were kept' : 'Draft restored') : '');
      if (packhousePanel) packhousePanel.refresh();
    }
    // Switching SOL: keep what was typed for the one being left, then show the other's.
    function onSolChange() {
      stash();
      activeSol = $('#qSol').value;
      activeEntry = defaultEntry(activeSol);
      renderSol();
    }
    // Switching between the saved quote(s) and "New quote" for the same SOL.
    function onEntryChange() {
      stash();
      activeEntry = $('#qEntry').value;
      renderSol();
    }
    // Jump straight to a logged quote (the Edit buttons under the message).
    function openQuote(sol, entry) {
      if (!data[sol]) return;
      stash();
      $('#qSol').value = sol;
      activeSol = sol; activeEntry = entry || '';
      renderSol();
      bootstrap.Offcanvas.getOrCreateInstance(drawerEl).show();
    }
    // The single weight / dimensions block feeds packaging and freight; every "Part: ..."
    // line in those sections is just a read-out of it.
    function dimsReadout() {
      // Catalog values arrive as "1.250" / "6.00"; show them the way a person would say them.
      const tidy = v => { const n = parseFloat(v); return Number.isFinite(n) ? String(n) : v.trim(); };
      const w = tidy($('#qDimW').value), l = tidy($('#qDimL').value);
      const wd = tidy($('#qDimWd').value), h = tidy($('#qDimH').value);
      const parts = [];
      if (w) parts.push(w + ' lb');
      if (l && wd && h) parts.push(l + ' × ' + wd + ' × ' + h + ' in');
      else [['L', l], ['W', wd], ['H', h]].forEach(p => { if (p[1]) parts.push(p[0] + ' ' + p[1] + ' in'); });
      const text = parts.length ? parts.join(' · ') : 'not entered';
      form.querySelectorAll('[data-dims-readout]').forEach(el => { el.textContent = text; });
    }
    ['#qDimW', '#qDimL', '#qDimWd', '#qDimH'].forEach(sel => $(sel).addEventListener('input', dimsReadout));
    form.addEventListener('click', e => {
      if (!e.target.closest('[data-dims-edit]')) return;
      $('#qDimsSection').open = true;
      $('#qDimsSection').scrollIntoView({ block: 'nearest' });
      $('#qDimW').focus();
    });
    function renderLines() {
      $('#qLine').classList.toggle('d-none', !$('#qModeSplit').checked);
      const lines = selectedLines();
      const first = lines[0];
      $('#qFacts').innerHTML = lines.length ? (
        '<div><strong>NSN:</strong> <span class="font-monospace">' + esc(first.nsn) + '</span>' +
        (lines.length > 1 ? ' <span class="text-body-secondary">+' + (lines.length - 1) + ' more line(s)</span>' : '') + '</div>' +
        '<div><strong>Item:</strong> ' + esc(first.nomen) + '</div>' +
        '<div><strong>Qty:</strong> ' + basisQty() + ' ' + esc(first.uoi) + (lines.length > 1 ? ' (all lines)' : '') + '</div>' +
        (first.days ? '<div><strong>Required delivery:</strong> ' + first.days + ' days</div>' : '')
      ) : '<div class="text-body-secondary">No lines.</div>';
      $('#qLeadHint').textContent = first && first.days ? 'SOL requires ' + first.days + ' days' : '';
      const d = first ? first.dims : null;
      // Dimensions follow the catalog until the rep types some; typed figures stay with the NSN
      // they were typed for.
      if (dimsEdited && first && dimsFor !== first.nsn) dimsEdited = false;
      if (d) {
        if (!dimsEdited) {
          $('#qDimW').value = d.weight; $('#qDimL').value = d.length; $('#qDimWd').value = d.width; $('#qDimH').value = d.height;
          $('#qDimSource').value = d.source;
        }
        $('#qDimsNote').textContent = dimsEdited ? '(edited)' : !d.known ? '(no catalog NSN record)'
          : d.verified ? '(last verified ' + d.verified + ')' : '(from catalog)';
        $('#qSaveDims').disabled = !d.known;
      }
      // The quantity being priced may just have changed (other SOL, Combined <-> Split, other
      // line): totals must be spread over the new quantity, and the derived side of each
      // unit / total pair must follow, or it keeps showing the old quantity's figure.
      rederive('#qPackUnit', '#qPackTotal');
      rederive('#qFreightUnit', '#qFreightTotal');
      const qty = basisQty();
      const spread = qty ? 'Totals are spread over ' + qty + ' unit' + (qty === 1 ? '' : 's') +
        (lines.length > 1 ? ' (all lines)' : '') + '.' : 'No quantity on this solicitation, so a total cannot be spread per unit.';
      form.querySelectorAll('[data-spread-hint]').forEach(el => { el.textContent = spread; });
      dimsReadout();
      recalc();
    }
    ['#qDimW', '#qDimL', '#qDimWd', '#qDimH', '#qDimSource'].forEach(sel => $(sel).addEventListener('input', () => {
      const first = selectedLines()[0];
      dimsEdited = true; dimsFor = first ? first.nsn : '';
      $('#qDimsNote').textContent = '(edited)';
    }));

    // Recompute the side of a unit / total pair the rep did NOT type, for the current quantity.
    function rederive(unitSel, totalSel) {
      const q = basisQty();
      const side = typedSide(unitSel, totalSel);
      if (side === 'unit') {
        $(totalSel).value = $(unitSel).value && q ? round(num($(unitSel).value) * q, 2).toFixed(2) : '';
      } else if (side === 'total') {
        $(unitSel).value = $(totalSel).value && q ? round(num($(totalSel).value) / q, 5).toString() : '';
      }
    }

    // Two-way unit <-> total for packaging and freight.
    function pairWire(unitSel, totalSel, sumSel) {
      $(unitSel).addEventListener('input', () => {
        const q = basisQty();
        $(totalSel).value = $(unitSel).value && q ? round(num($(unitSel).value) * q, 2).toFixed(2) : '';
        $(totalSel).dataset.derived = '1'; $(unitSel).dataset.derived = '';
        recalc();
      });
      $(totalSel).addEventListener('input', () => {
        const q = basisQty();
        $(unitSel).value = $(totalSel).value && q ? round(num($(totalSel).value) / q, 5).toString() : '';
        $(unitSel).dataset.derived = '1'; $(totalSel).dataset.derived = '';
        recalc();
      });
    }
    pairWire('#qPackUnit', '#qPackTotal');
    pairWire('#qFreightUnit', '#qFreightTotal');

    function perUnit(unitSel, totalSel) {
      const q = basisQty();
      if ($(totalSel).value && !$(totalSel).dataset.derived && q) return num($(totalSel).value) / q;
      return num($(unitSel).value);
    }

    function recalc() {
      const pack = perUnit('#qPackUnit', '#qPackTotal');
      const freight = perUnit('#qFreightUnit', '#qFreightTotal');
      const landed = round(num($('#qCost').value) + pack + freight, 5);
      $('#qPackSum').textContent = money(pack) + ' / unit';
      $('#qFreightSum').textContent = money(freight) + ' / unit';
      $('#qLanded').textContent = money(landed);
      if (markupMode === 'target') {
        const price = num($('#qPrice').value);
        $('#qPctOut').textContent = landed ? round((price / landed - 1) * 100, 2).toFixed(2) + '%' : '—';
      } else {
        const pct = num($('#qMarkup').value);
        $('#qPrice').value = landed ? round(landed * (1 + pct / 100), 2).toFixed(2) : '';
        $('#qPctOut').textContent = pct.toFixed(2) + '%';
      }
      // What the government pays for the quantity being quoted: the unit price times it.
      const qty = basisQty();
      $('#qQtyOut').textContent = qty;
      $('#qExtended').textContent = '$' + round(num($('#qPrice').value) * qty, 2)
        .toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    // Tip-screen markup pills.
    $('#qTips').addEventListener('click', e => {
      const pill = e.target.closest('[data-pct]');
      if (!pill) return;
      form.querySelectorAll('.quote-tip').forEach(p => p.classList.toggle('active', p === pill));
      const custom = pill.dataset.pct === 'custom';
      $('#qCustomWrap').classList.toggle('d-none', !custom);
      markupMode = 'pct'; $('#qTarget').value = '';
      $('#qMarkup').value = custom ? ($('#qCustomPct').value || '0') : pill.dataset.pct;
      if (custom) $('#qCustomPct').focus();
      recalc();
    });
    $('#qCustomPct').addEventListener('input', () => {
      markupMode = 'pct'; $('#qTarget').value = '';
      $('#qMarkup').value = $('#qCustomPct').value || '0';
      recalc();
    });
    // Typing a final price switches to target mode (server back-calculates markup).
    $('#qPrice').addEventListener('input', () => {
      markupMode = 'target';
      $('#qTarget').value = $('#qPrice').value;
      form.querySelectorAll('.quote-tip').forEach(p => p.classList.toggle('active', p.dataset.pct === 'custom'));
      $('#qCustomWrap').classList.remove('d-none');
      recalc();
    });
    ['#qCost'].forEach(sel => $(sel).addEventListener('input', recalc));

    // Packhouse picker (third-party packaging).
    $('#qPackSource').addEventListener('change', syncPackSource);
    $('#qPackhouse').addEventListener('input', debounce(() => {
      const q = $('#qPackhouse').value.trim();
      $('#qPackhouseId').value = '';
      if (q.length < 2) { $('#qPackhouseResults').innerHTML = ''; return; }
      fetch(searchUrl + '?q=' + encodeURIComponent(q)).then(r => r.json()).then(res => {
        const rows = res.results.slice().sort((a, b) => (b.packhouse ? 1 : 0) - (a.packhouse ? 1 : 0));
        $('#qPackhouseResults').innerHTML = rows.map(s =>
          '<button type="button" class="list-group-item list-group-item-action py-1" data-id="' + s.id + '" data-name="' + esc(s.name) + '">' +
          esc(s.name) + (s.packhouse ? ' <span class="badge text-bg-light border">Packhouse</span>' : '') + '</button>').join('');
      });
    }, 250));
    $('#qPackhouseResults').addEventListener('click', e => {
      const btn = e.target.closest('[data-id]');
      if (!btn) return;
      $('#qPackhouseId').value = btn.dataset.id;
      $('#qPackhouse').value = btn.dataset.name;
      $('#qPackhouseResults').innerHTML = '';
    });

    $('#qSol').addEventListener('change', onSolChange);
    $('#qEntry').addEventListener('change', onEntryChange);
    form.querySelectorAll('input[name="mode"]').forEach(r => r.addEventListener('change', renderLines));
    $('#qLine').addEventListener('change', renderLines);
    form.addEventListener('input', stashSoon);
    form.addEventListener('change', stashSoon);
    $('#qDraftClear').addEventListener('click', () => {
      const wasSaved = !!currentCard();
      discardDraft(activeKey());
      renderSol();
      updateSolOptions();
      draftNote(wasSaved ? 'Changes undone' : 'Cleared');
    });
    root.addEventListener('click', e => {
      const btn = e.target.closest('[data-edit-quote]');
      if (btn) openQuote(btn.dataset.sol, btn.dataset.entry);
    });

    // Packhouse quote requests (Packaging section). "Use" drops a recorded price into the
    // packaging fields and lets the normal unit <-> total wiring do the rest.
    if (window.QuotePackhouse) {
      packhousePanel = window.QuotePackhouse.initDrawer(form, Object.assign({
        solNumber: () => $('#qSol').value,
        solData: () => data[$('#qSol').value],
        lineId: () => {
          const card = currentCard();
          if (card) return card.line_ids.length === 1 && !card.covers_all ? String(card.line_ids[0]) : null;
          return $('#qModeSplit').checked ? $('#qLine').value : null;
        },
        applyQuote: req => {
          $('#qPackSource').value = 'THIRD_PARTY';
          $('#qPackSource').dispatchEvent(new Event('change'));
          $('#qPackhouseId').value = req.packhouse_id;
          $('#qPackhouse').value = req.name;
          $('#qPackhouseResults').innerHTML = '';
          $('#qPackUnit').value = String(parseFloat(req.unit));
          $('#qPackUnit').dispatchEvent(new Event('input'));
          window.showToast('info', 'Using ' + req.name + '\'s packaging price.');
        },
      }, phCtx));
    }

    form.addEventListener('submit', e => {
      e.preventDefault();
      $('#qError').classList.add('d-none');
      const fd = new FormData(form);
      // A new quote names the exact lines it covers (only ones this supplier has not quoted); a saved
      // quote keeps the lines it was saved for, which the server knows.
      if (!currentCard()) selectedLines().forEach(l => fd.append('line_ids', l.id));
      // Only send whichever side of each unit/total pair the rep typed.
      ['#qPackUnit', '#qPackTotal', '#qFreightUnit', '#qFreightTotal'].forEach(sel => {
        if ($(sel).dataset.derived) fd.set($(sel).name, '');
      });
      if (markupMode === 'target') fd.set('markup_pct', ''); else fd.set('target_price', '');
      $('#qSave').disabled = true;
      post(root.dataset.saveUrl, fd).then(res => {
        $('#qSave').disabled = false;
        if (!res.ok) {
          $('#qError').textContent = res.body.error || 'Could not save.';
          $('#qError').classList.remove('d-none');
          return;
        }
        // Saved: this SOL's draft has done its job. Lock first so a pending autosave cannot
        // write it back before the message reloads.
        draftsLocked = true;
        discardDraft(activeKey());
        window.showToast('success', res.body.message, 6000);
        bootstrap.Offcanvas.getOrCreateInstance(container.querySelector('#quoteDrawer')).hide();
        if (cfg.onSaved) cfg.onSaved(res.body);
      }).catch(() => {
        $('#qSave').disabled = false;
        $('#qError').textContent = 'Could not save. Check your connection and try again.';
        $('#qError').classList.remove('d-none');
      });
    });

    // Where to open: back where the rep left off (the first SOL with unsaved work, on its most recently
    // edited quote); else the first SOL with no quote logged yet; else, when every SOL has one, the
    // first SOL's saved quote -- so opening the tray always shows what was logged, never a blank form.
    loadDrafts();
    const solOptions = Array.from($('#qSol').options);
    const draftKeysFor = sol => Object.keys(drafts).filter(k => k === sol || k.indexOf(sol + '|') === 0);
    const resume = solOptions.find(o => draftKeysFor(o.value).length);
    const start = resume || solOptions.find(o => !o.dataset.logged);
    if (start) $('#qSol').value = start.value;
    activeSol = $('#qSol').value;
    const newest = draftKeysFor(activeSol).sort((a, b) => drafts[b].at - drafts[a].at)[0];
    activeEntry = newest ? (newest.indexOf('|') === -1 ? '' : newest.split('|')[1]) : defaultEntry(activeSol);
    updateSolOptions();
    renderSol();

    return {
      form: form,
      openQuote: openQuote,
      show: () => bootstrap.Offcanvas.getOrCreateInstance(drawerEl).show(),
      hide: () => bootstrap.Offcanvas.getOrCreateInstance(drawerEl).hide(),
    };
  }

  window.QuoteDrawer = { init: init };
})();
