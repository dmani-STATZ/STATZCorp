/*
 * Supplier capabilities (NSN / FSC lists that drive solicitation matching).
 *
 * One module, three hosts: the Capabilities page (drawer), a solicitation's
 * workspace (drawer) and the supplier detail page (inline). Every host gets the
 * same editor, because the editor is a server-rendered fragment
 * (quote/capabilities/_editor.html) that this script only brings to life.
 *
 *   QuoteCapabilities.openDrawer({url, title, onChange, onClose})
 *   QuoteCapabilities.mountEditor(container, url, {onChange})
 *   QuoteCapabilities.initImporter(root, {onChange})   // paste / file -> review -> add
 *   QuoteCapabilities.attachSupplierSearch(input, list, searchUrl, onPick)
 *   QuoteCapabilities.undoImport(url, csrfElement)
 *
 * The server is the only place NSNs / FSCs are parsed: the browser posts the
 * paste or file to the preview endpoint, draws what comes back, and posts the
 * same payload again to commit. Nothing here decides what a capability is.
 */
(function () {
  'use strict';

  var NF = new Intl.NumberFormat();
  function fmt(v) { return NF.format(v || 0); }
  function word(n, one, many) { return n === 1 ? one : (many || one + 's'); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function toast(type, message, ms) {
    if (window.showToast) window.showToast(type, message, ms); else console.log(type, message);
  }
  function csrfOf(el) {
    var holder = el && el.closest ? el.closest('[data-csrf]') : null;
    if (holder && holder.dataset.csrf) return holder.dataset.csrf;
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }
  function show() { Array.prototype.forEach.call(arguments, function (e) { e.classList.remove('d-none'); }); }
  function hide() { Array.prototype.forEach.call(arguments, function (e) { e.classList.add('d-none'); }); }
  function fmtSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return Math.round(bytes / 1024) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }
  function parts(nsns, fscs) {
    var out = [];
    if (nsns) out.push(fmt(nsns) + ' ' + word(nsns, 'NSN'));
    if (fscs) out.push(fmt(fscs) + ' ' + word(fscs, 'FSC'));
    return out.join(' and ') || 'nothing';
  }

  // Every request answers JSON. A redirect means the session ended or Quotes
  // access is missing -- say so instead of choking on a login page.
  function readJson(response) {
    if (response.redirected) {
      throw new Error('Your session ended, or you do not have Quotes access. Reload the page.');
    }
    return response.json().catch(function () { return {}; }).then(function (data) {
      if (!response.ok) throw new Error(data.error || 'Something went wrong (' + response.status + ').');
      return data;
    });
  }
  function postForm(url, formData, csrfEl) {
    return fetch(url, {
      method: 'POST', body: formData, credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrfOf(csrfEl), 'X-Requested-With': 'XMLHttpRequest' },
    }).then(readJson);
  }
  function fetchFragment(url) {
    return fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) {
        if (r.redirected) throw new Error('Your session ended, or you do not have Quotes access. Reload the page.');
        if (!r.ok) throw new Error('Could not load capabilities (' + r.status + ').');
        return r.text();
      });
  }

  // ── Supplier typeahead ─────────────────────────────────────────────────────
  function attachSupplierSearch(input, list, url, onPick, options) {
    if (!input || !list) return;
    var timer = null, seq = 0, results = [];
    var outside = !options || options.outside !== false;
    function close() { list.classList.add('d-none'); list.innerHTML = ''; }
    input.addEventListener('input', function () {
      clearTimeout(timer);
      var q = input.value.trim();
      if (q.length < 2) { close(); return; }
      timer = setTimeout(function () {
        var mine = ++seq;
        fetch(url + '?q=' + encodeURIComponent(q), { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (mine !== seq) return;
            results = data.results || [];
            list.innerHTML = results.length ? results.map(function (s) {
              return '<button type="button" class="list-group-item list-group-item-action" data-id="' + s.id + '">' +
                '<span class="fw-semibold">' + esc(s.name) + '</span> ' +
                '<span class="font-monospace small text-body-secondary">' + esc(s.cage) + '</span>' +
                (s.type ? '<div class="small text-body-secondary">' + esc(s.type) + '</div>' : '') +
                '</button>';
            }).join('') : '<div class="list-group-item small text-body-secondary">No suppliers found.</div>';
            list.classList.remove('d-none');
          })
          .catch(close);
      }, 200);
    });
    list.addEventListener('mousedown', function (e) { e.preventDefault(); });   // keep the input focused
    list.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-id]');
      if (!btn) return;
      var picked = results.filter(function (s) { return String(s.id) === btn.dataset.id; })[0];
      close();
      if (picked) onPick(picked);
    });
    input.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
    if (outside) {
      document.addEventListener('click', function (e) {
        if (e.target !== input && !list.contains(e.target)) close();
      });
    } else {
      input.addEventListener('blur', function () { setTimeout(close, 150); });
    }
  }

  function undoImport(url, csrfEl) {
    return postForm(url, new FormData(), csrfEl);
  }

  // ── Importer: paste or file -> review -> add ───────────────────────────────
  function initImporter(root, opts) {
    if (!root) return null;
    if (root._cap) return root._cap;
    opts = opts || {};

    function q(role) { return root.querySelector('[data-role="' + role + '"]'); }
    var el = {
      drop: q('drop'), file: q('file'), browse: q('browse'), text: q('text'), review: q('review'),
      chip: q('file-chip'), error: q('error'), mapping: q('mapping'), preview: q('preview'), done: q('done'),
    };
    var state = { file: null, mapping: null, assignments: {}, plan: null, seq: 0, requireSupplier: false };
    function supplierFixed() { return !!root.dataset.supplierId; }

    function reset() {
      state.mapping = null; state.assignments = {}; state.plan = null; state.seq++;
      hide(el.error, el.mapping, el.preview, el.done);
    }
    function showError(message) {
      el.error.className = 'alert alert-danger py-2 small mt-2 mb-0';
      el.error.textContent = message;
    }
    function busy(on) {
      el.review.disabled = on;
      el.review.innerHTML = on
        ? '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Reading…'
        : '<i class="bi bi-search" aria-hidden="true"></i> Review';
      el.preview.classList.toggle('cap-busy', on);
    }

    function formData() {
      var fd = new FormData();
      if (state.file) fd.append('file', state.file); else fd.append('text', el.text.value);
      if (root.dataset.supplierId) fd.append('supplier_id', root.dataset.supplierId);
      if (state.mapping) fd.append('mapping', JSON.stringify(state.mapping));
      if (Object.keys(state.assignments).length) fd.append('assignments', JSON.stringify(state.assignments));
      return fd;
    }

    function analyze() {
      hide(el.error, el.done);
      if (state.requireSupplier && !supplierFixed()) { showError('Pick which supplier this list is for first.'); return; }
      if (!state.file && !el.text.value.trim()) { showError('Paste a list or drop a file first.'); return; }
      var mine = ++state.seq;
      busy(true);
      postForm(root.dataset.previewUrl, formData(), root).then(function (plan) {
        if (mine !== state.seq) return;
        state.plan = plan;
        if (!state.mapping && plan.mapping) state.mapping = plan.mapping;
        render(plan);
      }).catch(function (err) {
        if (mine !== state.seq) return;
        hide(el.mapping, el.preview);
        showError(err.message);
      }).then(function () { if (mine === state.seq) busy(false); });
    }

    // ---- input -------------------------------------------------------------
    function setFile(file) {
      if (!file) return;
      state.file = file;
      el.text.value = '';
      reset();
      el.chip.innerHTML = '<i class="bi bi-file-earmark-spreadsheet" aria-hidden="true"></i> ' +
        '<strong>' + esc(file.name) + '</strong> <span class="text-body-secondary">' + fmtSize(file.size) + '</span>' +
        '<button type="button" class="btn-close" data-role="clear-file" aria-label="Remove file"></button>';
      show(el.chip);
      analyze();
    }
    function clearFile() {
      state.file = null;
      el.file.value = '';
      el.chip.innerHTML = '';
      hide(el.chip);
      reset();
    }

    el.browse.addEventListener('click', function (e) { e.stopPropagation(); el.file.click(); });
    el.drop.addEventListener('click', function () { el.file.click(); });
    el.drop.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); el.file.click(); }
    });
    el.file.addEventListener('change', function () { setFile(el.file.files[0]); });
    el.chip.addEventListener('click', function (e) { if (e.target.closest('[data-role="clear-file"]')) clearFile(); });

    // Dropping anywhere on the importer works; the browser must never navigate to the file.
    ['dragenter', 'dragover'].forEach(function (t) {
      root.addEventListener(t, function (e) {
        e.preventDefault();
        if (e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') !== -1) {
          el.drop.classList.add('is-over');
        }
      });
    });
    root.addEventListener('dragleave', function (e) {
      if (!root.contains(e.relatedTarget)) el.drop.classList.remove('is-over');
    });
    root.addEventListener('drop', function (e) {
      e.preventDefault();
      el.drop.classList.remove('is-over');
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
    });

    el.text.addEventListener('input', function () {
      if (state.file) clearFile();
      if (state.plan || !el.done.classList.contains('d-none')) reset();   // the review is stale now
    });
    el.text.addEventListener('paste', function () {
      setTimeout(function () { if (el.text.value.trim()) { if (state.file) clearFile(); analyze(); } }, 0);
    });
    el.text.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); analyze(); }
    });
    el.review.addEventListener('click', analyze);

    // ---- rendering ---------------------------------------------------------
    function renderMapping(plan) {
      var t = plan.table;
      if (!t || t.width < 2) { hide(el.mapping); return; }
      var multi = !supplierFixed();
      var roles = plan.mapping.roles;
      var options = multi
        ? [['ignore', 'Ignore'], ['cage', 'Supplier CAGE'], ['name', 'Supplier name'], ['items', 'NSNs / FSCs']]
        : [['ignore', 'Ignore'], ['items', 'NSNs / FSCs']];
      var head = '', body = '';
      t.columns.forEach(function (label, j) {
        head += '<th class="' + (roles[j] === 'ignore' ? 'cap-col-ignored' : '') + '">' +
          '<div class="cap-col-label" title="' + esc(label) + '">' + esc(label) + '</div>' +
          '<select class="form-select form-select-sm" data-col="' + j + '" aria-label="What ' + esc(label) + ' holds">' +
          options.map(function (o) {
            return '<option value="' + o[0] + '"' + (o[0] === roles[j] ? ' selected' : '') + '>' + o[1] + '</option>';
          }).join('') + '</select></th>';
      });
      t.sample.forEach(function (row) {
        body += '<tr>' + row.map(function (c, j) {
          return '<td class="' + (roles[j] === 'ignore' ? 'cap-col-ignored' : '') + '" title="' + esc(c) + '">' + esc(c) + '</td>';
        }).join('') + '</tr>';
      });
      el.mapping.innerHTML =
        '<div class="cap-map">' +
        '<div class="cap-map-head"><strong>Check the columns</strong>' +
        '<span class="small text-body-secondary">We guessed from your data. Change anything that looks wrong.</span>' +
        '<label class="form-check form-check-inline ms-auto small mb-0">' +
        '<input class="form-check-input" type="checkbox" data-role="hdr"' + (plan.mapping.header ? ' checked' : '') + '> First row is a header</label></div>' +
        '<div class="table-responsive"><table class="table table-sm cap-map-table mb-1"><thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table></div>' +
        '<div class="small text-body-secondary">' + fmt(t.rows) + ' ' + word(t.rows, 'row') +
        (plan.note ? ' &middot; ' + esc(plan.note) : '') + '</div></div>';
      show(el.mapping);
    }

    function tiles(s) {
      function tile(cls, value, label) {
        return '<div class="cap-tile ' + cls + '"><span class="cap-tile-value">' + fmt(value) + '</span>' +
          '<span class="cap-tile-label">' + label + '</span></div>';
      }
      return '<div class="cap-tiles">' +
        tile('cap-tile-nsn', s.nsns_new, 'new ' + word(s.nsns_new, 'NSN')) +
        tile('cap-tile-fsc', s.fscs_new, 'new ' + word(s.fscs_new, 'FSC')) +
        tile('', s.nsns_existing + s.fscs_existing, 'already on file') +
        tile(s.unreadable ? 'cap-tile-warn' : '', s.unreadable, 'could not be read') +
        '</div>';
    }

    function impact(plan) {
      var i = plan.impact || {}, s = plan.summary;
      if (!s.pairings_new) {
        return '<div class="cap-impact cap-impact-muted"><i class="bi bi-info-circle" aria-hidden="true"></i>' +
          '<div>Nothing new to add. Everything readable is already on file.</div></div>';
      }
      if (i.solicitations > 0) {
        return '<div class="cap-impact"><i class="bi bi-lightning-charge-fill" aria-hidden="true"></i><div>' +
          'Adding these links suppliers to <strong>' + fmt(i.solicitations) + ' open ' + word(i.solicitations, 'solicitation') + '</strong>' +
          (i.newly_matched
            ? ', and <strong>' + fmt(i.newly_matched) + '</strong> of them ' + word(i.newly_matched, 'moves', 'move') + ' from Unmatched to Matched.'
            : '.') +
          '</div></div>';
      }
      return '<div class="cap-impact cap-impact-muted"><i class="bi bi-info-circle" aria-hidden="true"></i>' +
        '<div>None of your open solicitations use these yet. They will match future imports automatically.</div></div>';
    }

    function supplierRow(sp, showName) {
      var chips = sp.fscs.map(function (f) {
        return '<span class="cap-chip cap-chip-fsc cap-chip-static" title="' + fmt(f.open) +
          ' open solicitation(s) have a line in this class">' + esc(f.fsc) +
          '<span class="cap-chip-note">' + (f.open ? fmt(f.open) + ' open' : 'none open') + '</span></span>';
      }).join('');
      var badges = [];
      if (sp.nsns_new) badges.push('<span class="badge quote-lineage quote-lineage-nsn">+' + fmt(sp.nsns_new) + ' NSN</span>');
      if (sp.fscs_new) badges.push('<span class="badge quote-lineage quote-lineage-fsc">+' + fmt(sp.fscs_new) + ' FSC</span>');
      var have = sp.nsns_existing + sp.fscs_existing;
      if (have) badges.push('<span class="small text-body-secondary">' + fmt(have) + ' already on file</span>');
      var sample = sp.sample.length
        ? '<div class="small text-body-secondary font-monospace cap-sample-line">' + sp.sample.map(esc).join(' &middot; ') +
          (sp.nsns_new > sp.sample.length ? ' &middot; +' + fmt(sp.nsns_new - sp.sample.length) + ' more' : '') + '</div>'
        : '';
      return '<div class="cap-sup-row"><div class="cap-sup-main">' +
        (showName ? '<div class="fw-semibold">' + esc(sp.name) + ' <span class="font-monospace small text-body-secondary">' + esc(sp.cage) + '</span></div>' : '') +
        (chips ? '<div class="cap-chips mt-1">' + chips + '</div>' : '') + sample +
        '</div><div class="cap-sup-badges">' + badges.join(' ') + '</div></div>';
    }

    function suppliersBlock(plan) {
      if (!plan.suppliers.length) return '';
      var multi = !supplierFixed();
      var rows = plan.suppliers.map(function (sp) { return supplierRow(sp, multi); }).join('');
      var more = plan.suppliers_hidden ? '<div class="small text-body-secondary pt-2">&hellip;and ' + fmt(plan.suppliers_hidden) + ' more suppliers.</div>' : '';
      return '<div class="cap-block"><h3 class="cap-block-title">' +
        (multi ? 'Suppliers <span class="cap-block-sub">' + fmt(plan.suppliers.length + (plan.suppliers_hidden || 0)) + '</span>' : 'What will be added') +
        '</h3>' + rows + more + '</div>';
    }

    var REASONS = {
      unknown: 'Not in the supplier directory',
      ambiguous: 'Matches more than one supplier',
      archived: 'Archived supplier',
      blank: 'No supplier named on these rows',
    };
    function unresolvedBlock(plan) {
      if (!plan.unresolved.length) return '';
      var rows = plan.unresolved.map(function (u) {
        var control;
        if (u.assigned === 'skip') {
          control = '<span class="small text-body-secondary">Skipped</span> ' +
            '<button type="button" class="btn btn-link btn-sm p-0" data-unassign="' + esc(u.key) + '">Undo</button>';
        } else if (u.assigned) {
          control = '<span class="small"><i class="bi bi-arrow-right" aria-hidden="true"></i> <strong>' + esc(u.assigned_name) + '</strong></span> ' +
            '<button type="button" class="btn btn-link btn-sm p-0" data-unassign="' + esc(u.key) + '">Change</button>';
        } else {
          control = (u.reason === 'ambiguous' ? (u.candidates || []) : []).map(function (c) {
            return '<button type="button" class="btn btn-outline-secondary btn-sm" data-assign="' + esc(u.key) + '" data-supplier="' + c.id + '">' +
              'Use ' + esc(c.name) + (c.cage ? ' (' + esc(c.cage) + ')' : '') + '</button>';
          }).join(' ') +
          '<div class="cap-adder cap-adder-inline"><input type="search" class="form-control form-control-sm" autocomplete="off" ' +
          'placeholder="Find a supplier&hellip;" data-assign-search="' + esc(u.key) + '" aria-label="Find the supplier for ' + esc(u.label) + '">' +
          '<div class="list-group cap-adder-results d-none"></div></div>' +
          '<button type="button" class="btn btn-link btn-sm text-body-secondary" data-skip="' + esc(u.key) + '">Skip</button>';
        }
        return '<div class="cap-unres-row"><div class="cap-unres-what"><div class="fw-semibold">' + esc(u.label) + '</div>' +
          '<div class="small text-body-secondary">' + (REASONS[u.reason] || 'Not placed') + ' &middot; ' +
          fmt(u.rows) + ' ' + word(u.rows, 'row') + ', ' + fmt(u.items) + ' ' + word(u.items, 'pairing') + '</div></div>' +
          '<div class="cap-unres-ctl">' + control + '</div></div>';
      }).join('');
      return '<div class="cap-block"><h3 class="cap-block-title">Suppliers we could not place</h3>' +
        '<p class="small text-body-secondary mb-2">These rows are left out unless you pick a supplier for them.</p>' + rows + '</div>';
    }

    function unreadableBlock(plan) {
      if (!plan.unreadable.length) return '';
      var extra = plan.summary.unreadable - plan.unreadable.length;
      return '<details class="cap-unread"><summary>' + fmt(plan.summary.unreadable) + ' ' +
        word(plan.summary.unreadable, 'item') + ' could not be read</summary><ul>' +
        plan.unreadable.map(function (u) {
          return '<li><span class="text-body-secondary">Row ' + fmt(u.row) + '</span> <code>' + esc(u.text) + '</code> ' + esc(u.reason) + '</li>';
        }).join('') + (extra > 0 ? '<li class="text-body-secondary">&hellip;and ' + fmt(extra) + ' more.</li>' : '') + '</ul></details>';
    }

    function footer(plan) {
      var s = plan.summary, multi = !supplierFixed();
      var label = 'Add ' + parts(s.nsns_new, s.fscs_new) +
        (multi && s.suppliers > 1 ? ' to ' + fmt(s.suppliers) + ' suppliers' : '');
      return '<div class="cap-footer">' +
        '<button type="button" class="btn btn-primary" data-role="commit"' + (plan.can_commit ? '' : ' disabled') + '>' +
        (plan.can_commit ? label : 'Nothing to add') + '</button>' +
        '<button type="button" class="btn btn-link btn-sm" data-role="start-over">Start over</button>' +
        '<span class="small text-body-secondary ms-auto">Nothing is saved until you click Add. Imports can be undone.</span></div>';
    }

    function renderPreview(plan) {
      var html = '';
      if (plan.problems.length) {
        html += '<div class="alert alert-danger py-2 small mb-3">' + plan.problems.map(esc).join('<br>') + '</div>';
      }
      if (plan.truncated) {
        html += '<div class="alert alert-warning py-2 small mb-3">Only the first 100,000 rows were read.</div>';
      }
      if (!plan.problems.length) {
        html += tiles(plan.summary) + impact(plan) + suppliersBlock(plan) + unresolvedBlock(plan);
      }
      html += unreadableBlock(plan);
      if (!plan.problems.length) html += footer(plan);
      el.preview.innerHTML = html;
      show(el.preview);

      Array.prototype.forEach.call(el.preview.querySelectorAll('[data-assign-search]'), function (input) {
        attachSupplierSearch(input, input.parentNode.querySelector('.cap-adder-results'),
          root.dataset.searchUrl, function (s) {
            state.assignments[input.dataset.assignSearch] = s.id;
            analyze();
          }, { outside: false });
      });
    }

    function render(plan) { renderMapping(plan); renderPreview(plan); }

    // ---- interactions inside the review -----------------------------------
    el.mapping.addEventListener('change', function (e) {
      if (!state.mapping) return;
      var sel = e.target.closest('select[data-col]');
      if (sel) {
        var j = parseInt(sel.dataset.col, 10), role = sel.value;
        if (role === 'cage' || role === 'name') {   // one CAGE column, one name column
          state.mapping.roles = state.mapping.roles.map(function (r, k) { return k !== j && r === role ? 'ignore' : r; });
        }
        state.mapping.roles[j] = role;
        analyze();
      } else if (e.target.matches('[data-role="hdr"]')) {
        state.mapping.header = e.target.checked;
        analyze();
      }
    });

    el.preview.addEventListener('click', function (e) {
      var btn = e.target.closest('button');
      if (!btn) return;
      if (btn.dataset.assign) { state.assignments[btn.dataset.assign] = parseInt(btn.dataset.supplier, 10); analyze(); }
      else if (btn.dataset.skip) { state.assignments[btn.dataset.skip] = 'skip'; analyze(); }
      else if (btn.dataset.unassign) { delete state.assignments[btn.dataset.unassign]; analyze(); }
      else if (btn.dataset.role === 'start-over') { clearFile(); el.text.value = ''; el.text.focus(); }
      else if (btn.dataset.role === 'commit') commit(btn);
    });

    function commit(btn) {
      var original = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Adding&hellip;';
      postForm(root.dataset.commitUrl, formData(), root).then(function (res) {
        done(res);
        toast('success', 'Added ' + parts(res.nsns_added, res.fscs_added) + '.');
        if (opts.onChange) opts.onChange(res);
      }).catch(function (err) {
        btn.disabled = false;
        btn.innerHTML = original;
        showError(err.message);
      });
    }

    function done(res) {
      var multi = !supplierFixed();
      var line = res.solicitations_matched
        ? '<strong>' + fmt(res.solicitations_matched) + '</strong> open ' + word(res.solicitations_matched, 'solicitation') + ' moved to Matched'
        : (res.matches_created
          ? fmt(res.matches_created) + ' ' + word(res.matches_created, 'solicitation') + ' linked to a supplier'
          : 'No open solicitations use these yet');
      if (res.already_on_file) line += '. ' + fmt(res.already_on_file) + ' already on file ' + word(res.already_on_file, 'was', 'were') + ' skipped';
      var actions = '';
      if (res.solicitations_matched) {
        actions += '<a class="btn btn-outline-secondary btn-sm" href="' + esc(root.dataset.queueUrl) + '?tab=MATCHED">See Matched</a> ';
      }
      actions += '<button type="button" class="btn btn-outline-secondary btn-sm" data-role="again">Add more</button> ' +
        '<button type="button" class="btn btn-link btn-sm text-danger" data-role="undo" data-url="' + esc(res.undo_url) + '">Undo this import</button>';
      el.done.innerHTML = '<div class="cap-done"><i class="bi bi-check-circle-fill" aria-hidden="true"></i>' +
        '<div class="flex-grow-1"><div class="fw-semibold">Added ' + parts(res.nsns_added, res.fscs_added) +
        (multi && res.suppliers > 1 ? ' across ' + fmt(res.suppliers) + ' suppliers' : '') + '.</div>' +
        '<div class="small">' + line + '.</div></div><div class="cap-done-actions">' + actions + '</div></div>';
      hide(el.mapping, el.preview, el.error);
      show(el.done);
      clearFile();
      el.text.value = '';
      show(el.done);   // clearFile() -> reset() hides it; show it again after the inputs are cleared
    }

    el.done.addEventListener('click', function (e) {
      var btn = e.target.closest('button');
      if (!btn) return;
      if (btn.dataset.role === 'again') { hide(el.done); el.text.focus(); }
      if (btn.dataset.role === 'undo') {
        if (btn.dataset.armed !== '1') {
          btn.dataset.armed = '1';
          btn.textContent = 'Really undo?';
          setTimeout(function () { btn.dataset.armed = ''; btn.textContent = 'Undo this import'; }, 4000);
          return;
        }
        btn.disabled = true;
        undoImport(btn.dataset.url, root).then(function (res) {
          hide(el.done);
          toast('success', 'Undone: removed ' + parts(res.nsns, res.fscs) + '.' +
            (res.returned_to_unmatched ? ' ' + fmt(res.returned_to_unmatched) + ' ' + word(res.returned_to_unmatched, 'solicitation') + ' back to Unmatched.' : ''));
          if (opts.onChange) opts.onChange(res);
        }).catch(function (err) { btn.disabled = false; toast('error', err.message); });
      }
    });

    var api = {
      analyze: analyze,
      setSupplier: function (s) {
        if (s) { root.dataset.supplierId = s.id; root.dataset.supplierName = s.name; }
        else { delete root.dataset.supplierId; delete root.dataset.supplierName; }
        if (state.file || el.text.value.trim()) { state.mapping = null; state.assignments = {}; analyze(); }
      },
      setRequireSupplier: function (flag) { state.requireSupplier = !!flag; },
    };
    root._cap = api;
    return api;
  }

  // ── Editor: one supplier's lists ───────────────────────────────────────────
  function initEditor(root, opts) {
    if (!root) return null;
    if (root._cap) return root._cap;
    opts = opts || {};
    var state = { q: '', page: 1, picked: {}, timer: null };

    function refresh() {
      var params = new URLSearchParams();
      if (state.q) params.set('q', state.q);
      if (state.page > 1) params.set('page', state.page);
      var focused = document.activeElement && document.activeElement.matches &&
        document.activeElement.matches('[data-role="filter"]');
      return fetchFragment(root.dataset.editorUrl + (params.toString() ? '?' + params : '')).then(function (html) {
        var tmp = document.createElement('div');
        tmp.innerHTML = html;
        ['live-top', 'live-bottom'].forEach(function (role) {
          var fresh = tmp.querySelector('[data-role="' + role + '"]');
          var current = root.querySelector('[data-role="' + role + '"]');
          if (fresh && current) current.innerHTML = fresh.innerHTML;
        });
        state.picked = {};
        var filter = root.querySelector('[data-role="filter"]');
        if (focused && filter) { filter.focus(); filter.setSelectionRange(filter.value.length, filter.value.length); }
      }).catch(function (err) { toast('error', err.message); });
    }

    function updateBulk() {
      var n = Object.keys(state.picked).length;
      var bar = root.querySelector('[data-role="bulkbar"]');
      if (!bar) return;
      bar.classList.toggle('d-none', n === 0);
      var count = bar.querySelector('[data-role="picked-count"]');
      if (count) count.textContent = fmt(n);
    }

    function armed(btn, run, armedText) {
      if (btn.dataset.armed === '1') {
        clearTimeout(btn._timer);
        btn.dataset.armed = '';
        btn.classList.remove('cap-armed');
        run();
        return;
      }
      var original = btn.innerHTML;
      btn.dataset.armed = '1';
      btn.classList.add('cap-armed');
      btn.innerHTML = armedText || 'Remove?';
      btn._timer = setTimeout(function () {
        btn.dataset.armed = '';
        btn.classList.remove('cap-armed');
        btn.innerHTML = original;
      }, 3500);
    }

    function remove(payload) {
      return fetch(root.dataset.removeUrl, {
        method: 'POST', credentials: 'same-origin', body: JSON.stringify(payload),
        headers: {
          'Content-Type': 'application/json', 'X-CSRFToken': csrfOf(root), 'X-Requested-With': 'XMLHttpRequest',
        },
      }).then(readJson).then(function (res) {
        var msg = 'Removed ' + parts(res.nsns, res.fscs) + '.';
        if (res.matches_removed) {
          msg += ' ' + fmt(res.matches_removed) + ' solicitation ' + word(res.matches_removed, 'link') + ' dropped' +
            (res.returned_to_unmatched ? ', ' + fmt(res.returned_to_unmatched) + ' back to Unmatched' : '') + '.';
        }
        toast('success', msg);
        if (opts.onChange) opts.onChange(res);
        return refresh();
      }).catch(function (err) { toast('error', err.message); });
    }

    root.addEventListener('click', function (e) {
      var btn = e.target.closest('button');
      if (!btn) return;
      if (btn.hasAttribute('data-remove-fsc')) {
        armed(btn, function () { remove({ fscs: [btn.dataset.removeFsc] }); }, 'Remove?');
      } else if (btn.hasAttribute('data-remove-one')) {
        var row = btn.closest('tr');
        armed(btn, function () { remove({ nsns: [row.dataset.nsn] }); }, 'Remove?');
      } else if (btn.hasAttribute('data-remove-picked')) {
        armed(btn, function () { remove({ nsns: Object.keys(state.picked) }); }, 'Sure?');
      } else if (btn.hasAttribute('data-page') && btn.dataset.page) {
        state.page = parseInt(btn.dataset.page, 10) || 1;
        refresh();
      }
    });

    root.addEventListener('change', function (e) {
      if (e.target.matches('[data-pick]')) {
        var nsn = e.target.closest('tr').dataset.nsn;
        if (e.target.checked) state.picked[nsn] = true; else delete state.picked[nsn];
        updateBulk();
      } else if (e.target.matches('[data-pick-all]')) {
        Array.prototype.forEach.call(root.querySelectorAll('[data-pick]'), function (box) {
          box.checked = e.target.checked;
          var nsn = box.closest('tr').dataset.nsn;
          if (box.checked) state.picked[nsn] = true; else delete state.picked[nsn];
        });
        updateBulk();
      }
    });

    root.addEventListener('input', function (e) {
      if (!e.target.matches('[data-role="filter"]')) return;
      clearTimeout(state.timer);
      state.timer = setTimeout(function () {
        state.q = e.target.value.trim();
        state.page = 1;
        refresh();
      }, 250);
    });

    initImporter(root.querySelector('[data-role="importer"]'), {
      onChange: function (res) {
        if (opts.onChange) opts.onChange(res);
        state.page = 1;
        refresh();
      },
    });

    var api = { refresh: refresh };
    root._cap = api;
    return api;
  }

  function mountEditor(container, url, opts) {
    container.innerHTML = '<div class="small text-body-secondary py-3">Loading capabilities&hellip;</div>';
    return fetchFragment(url).then(function (html) {
      container.innerHTML = html;
      return initEditor(container.querySelector('[data-role="editor"]'), opts);
    }).catch(function (err) {
      container.innerHTML = '<div class="alert alert-warning small mb-0">' + esc(err.message) + '</div>';
    });
  }

  function openDrawer(cfg) {
    var el = document.getElementById('capDrawer');
    if (!el) {
      el = document.createElement('div');
      el.id = 'capDrawer';
      el.className = 'offcanvas offcanvas-end cap-drawer';
      el.tabIndex = -1;
      el.setAttribute('aria-labelledby', 'capDrawerLabel');
      el.innerHTML = '<div class="offcanvas-header"><h5 class="offcanvas-title" id="capDrawerLabel"></h5>' +
        '<button type="button" class="btn-close" data-bs-dismiss="offcanvas" aria-label="Close"></button></div>' +
        '<div class="offcanvas-body"></div>';
      document.body.appendChild(el);
    }
    el.querySelector('.offcanvas-title').textContent = cfg.title || 'Capabilities';
    var body = el.querySelector('.offcanvas-body');
    var changed = false;
    function onHidden() {
      el.removeEventListener('hidden.bs.offcanvas', onHidden);
      body.innerHTML = '';
      if (cfg.onClose) cfg.onClose(changed);
    }
    el.addEventListener('hidden.bs.offcanvas', onHidden);
    mountEditor(body, cfg.url, {
      onChange: function (res) { changed = true; if (cfg.onChange) cfg.onChange(res); },
    });
    bootstrap.Offcanvas.getOrCreateInstance(el).show();
  }

  window.QuoteCapabilities = {
    openDrawer: openDrawer,
    mountEditor: mountEditor,
    initEditor: initEditor,
    initImporter: initImporter,
    attachSupplierSearch: attachSupplierSearch,
    undoImport: undoImport,
  };
})();
