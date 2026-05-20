/**
 * PO Snippet Library
 * Manages the offcanvas drawer, snippet CRUD, clipboard copy, and filtering.
 */

/** Bootstrap 5.x-safe: getInstance || new (matches contract_management modal pattern). */
function poSnippetOffcanvas() {
    const el = document.getElementById('poSnippetsOffcanvas');
    if (!el || !window.bootstrap?.Offcanvas) return null;
    return bootstrap.Offcanvas.getInstance(el) || new bootstrap.Offcanvas(el);
}

function poSnippetEditorModal() {
    const el = document.getElementById('snippetEditorModal');
    if (!el || !window.bootstrap?.Modal) return null;
    return bootstrap.Modal.getInstance(el) || new bootstrap.Modal(el);
}

const POSnippets = (() => {
    let _all = [];
    let _rendered = [];
    let _quill = null;

    const el = () => document.getElementById('poSnippetsOffcanvas');
    const url = (name, id) => {
        const base = el()?.dataset?.urlBase || '/contracts/api/po-snippets/';
        if (name === 'list')   return base;
        if (name === 'create') return base + 'create/';
        if (name === 'update') return base + `${id}/update/`;
        if (name === 'delete') return base + `${id}/delete/`;
    };

    function csrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value
            || getCookie('csrftoken');
    }
    function getCookie(name) {
        let v = null;
        document.cookie.split(';').forEach(c => {
            const [k, val] = c.trim().split('=');
            if (k === name) v = decodeURIComponent(val);
        });
        return v;
    }

    function _initQuill() {
        if (_quill) return;
        _quill = new Quill('#snippetEditorQuill', {
            theme: 'snow',
            modules: {
                toolbar: [
                    ['bold', 'italic', 'underline'],
                    [{ list: 'ordered' }, { list: 'bullet' }],
                    ['clean'],
                ],
            },
            placeholder: 'Paste or type the paragraph text…',
        });
    }

    async function load() {
        const spinner = document.getElementById('snippetListSpinner');
        if (spinner) spinner.style.display = 'block';
        try {
            const res = await fetch(url('list'), { credentials: 'same-origin' });
            const data = await res.json();
            _all = data.snippets || [];
            populateCategoryFilter();
            renderList();
        } catch (e) {
            const container = document.getElementById('snippetList');
            if (container) {
                container.innerHTML =
                    '<p class="text-danger p-3">Failed to load snippets.</p>';
            }
        } finally {
            if (spinner) spinner.style.display = 'none';
        }
    }

    function populateCategoryFilter() {
        const cats = [...new Set(_all.map(s => s.category).filter(Boolean))].sort();
        const sel = document.getElementById('snippetCategoryFilter');
        if (!sel) return;
        const current = sel.value;
        sel.innerHTML = '<option value="">All Categories</option>';
        cats.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c;
            opt.textContent = c;
            if (c === current) opt.selected = true;
            sel.appendChild(opt);
        });

        const dl = document.getElementById('snippetCategoryDatalist');
        if (dl) {
            dl.innerHTML = '';
            cats.forEach(c => {
                const o = document.createElement('option');
                o.value = c;
                dl.appendChild(o);
            });
        }
    }

    function renderList() {
        const catFilter = (document.getElementById('snippetCategoryFilter')?.value || '').toLowerCase();
        const searchFilter = (document.getElementById('snippetSearch')?.value || '').toLowerCase();

        _rendered = _all.filter(s => {
            const matchCat = !catFilter || (s.category || '').toLowerCase() === catFilter;
            const matchSearch = !searchFilter
                || s.title.toLowerCase().includes(searchFilter)
                || s.body.toLowerCase().includes(searchFilter)
                || (s.category || '').toLowerCase().includes(searchFilter);
            return matchCat && matchSearch;
        });

        const container = document.getElementById('snippetList');
        if (!container) return;

        if (_rendered.length === 0) {
            container.innerHTML = '<p class="text-muted p-3">No snippets match your filters.</p>';
            return;
        }

        const groups = {};
        _rendered.forEach(s => {
            const key = s.category || '(Uncategorized)';
            if (!groups[key]) groups[key] = [];
            groups[key].push(s);
        });

        let html = '';
        Object.keys(groups).sort().forEach(cat => {
            html += `<h6 class="text-muted text-uppercase small fw-semibold mt-3 mb-1 px-1"
                         style="letter-spacing:.06em; border-bottom:1px solid var(--bs-border-color); padding-bottom:4px;">
                        ${escapeHtml(cat)}
                     </h6>`;
            groups[cat].forEach(s => {
                html += snippetCard(s);
            });
        });

        container.innerHTML = html;
    }

    function snippetCard(s) {
        const plainPreview = (s.body || '')
            .replace(/<[^>]+>/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
        const preview = plainPreview.length > 160
            ? plainPreview.slice(0, 160) + '…'
            : plainPreview;

        return `
        <div class="card mb-2 snippet-card" data-id="${s.id}" style="border-left: 3px solid var(--bs-primary);">
          <div class="card-body py-2 px-3">
            <div class="d-flex align-items-start justify-content-between gap-2">
              <div class="flex-grow-1 min-w-0">
                <div class="fw-semibold text-truncate" style="font-size:.9rem;">${escapeHtml(s.title)}</div>
                <div class="text-muted mt-1" style="font-size:.8rem; white-space:pre-wrap; max-height:60px; overflow:hidden;">${escapeHtml(preview)}</div>
              </div>
              <div class="d-flex gap-1 flex-shrink-0 ms-2">
                <button class="btn btn-sm btn-outline-secondary" style="font-size:.75rem; padding:2px 8px;"
                        onclick="POSnippets.copyPlain(${s.id})" title="Copy as plain text">
                  Copy Text
                </button>
                <button class="btn btn-sm btn-outline-primary" style="font-size:.75rem; padding:2px 8px;"
                        onclick="POSnippets.copyHtml(${s.id})" title="Copy with formatting (paste into Word or Outlook)">
                  Copy Formatted
                </button>
                <button class="btn btn-sm btn-outline-secondary" style="font-size:.75rem; padding:2px 8px;"
                        onclick="POSnippets.openEditor(${s.id})" title="Edit">
                  Edit
                </button>
                <button class="btn btn-sm btn-outline-danger" style="font-size:.75rem; padding:2px 8px;"
                        onclick="POSnippets.deleteSnippet(${s.id})" title="Delete">
                  Del
                </button>
              </div>
            </div>
          </div>
        </div>`;
    }

    function escapeHtml(str) {
        const d = document.createElement('div');
        d.textContent = str || '';
        return d.innerHTML;
    }

    function copyPlain(id) {
        const snippet = _all.find(s => s.id === id);
        if (!snippet) return;
        const tmp = document.createElement('div');
        tmp.innerHTML = snippet.body || '';
        const plain = (tmp.textContent || tmp.innerText || '').trim();
        navigator.clipboard.writeText(plain).then(() => {
            _flashCopyBtn(id, 'copy-plain', '✓ Copied');
        }).catch(() => {
            alert('Copy failed — your browser may require HTTPS or a permission grant.');
        });
    }

    function copyHtml(id) {
        const snippet = _all.find(s => s.id === id);
        if (!snippet) return;
        const html = snippet.body || '';
        const tmp = document.createElement('div');
        tmp.innerHTML = html;
        const plain = (tmp.textContent || tmp.innerText || '').trim();
        const blob = new Blob(
            [`<html><body>${html}</body></html>`],
            { type: 'text/html' }
        );
        const plainBlob = new Blob([plain], { type: 'text/plain' });
        const item = new ClipboardItem({
            'text/html': blob,
            'text/plain': plainBlob,
        });
        navigator.clipboard.write([item]).then(() => {
            _flashCopyBtn(id, 'copy-html', '✓ Copied');
        }).catch(() => {
            navigator.clipboard.writeText(plain).then(() => {
                _flashCopyBtn(id, 'copy-html', '✓ Copied (text)');
            });
        });
    }

    function _flashCopyBtn(id, btnClass, label) {
        const card = document.querySelector(`.snippet-card[data-id="${id}"]`);
        if (!card) return;
        const btns = card.querySelectorAll('button');
        const titleMap = {
            'copy-plain': 'Copy as plain text',
            'copy-html':  'Copy with formatting (paste into Word or Outlook)',
        };
        const btn = [...btns].find(b => b.title === titleMap[btnClass]);
        if (!btn) return;
        const orig = btn.textContent;
        const origClass = btn.className;
        btn.textContent = label;
        btn.classList.add('btn-success');
        btn.classList.remove('btn-outline-secondary', 'btn-outline-primary');
        setTimeout(() => {
            btn.textContent = orig;
            btn.className = origClass;
        }, 1800);
    }

    function openEditor(id) {
        const modal = bootstrap.Modal.getOrCreateInstance(
            document.getElementById('snippetEditorModal')
        );
        document.getElementById('snippetEditorId').value = id || '';

        if (id) {
            const s = _all.find(x => x.id === id);
            if (!s) return;
            document.getElementById('snippetEditorLabel').textContent = 'Edit Snippet';
            document.getElementById('snippetEditorTitle').value = s.title;
            document.getElementById('snippetEditorCategory').value = s.category || '';
            document.getElementById('snippetEditorSortOrder').value = s.sort_order;
            // Load into Quill only if already initialized (first open defers
            // to the shown.bs.modal handler below)
            if (_quill) {
                _quill.clipboard.dangerouslyPasteHTML(s.body || '');
            }
        } else {
            document.getElementById('snippetEditorLabel').textContent = 'New Snippet';
            document.getElementById('snippetEditorTitle').value = '';
            document.getElementById('snippetEditorCategory').value = '';
            document.getElementById('snippetEditorSortOrder').value = '0';
            if (_quill) {
                _quill.setContents([]);
            }
        }
        modal.show();
    }

    async function saveSnippet() {
        const id = document.getElementById('snippetEditorId').value;
        const body = _quill ? _quill.root.innerHTML.trim() : '';
        const payload = {
            title:      document.getElementById('snippetEditorTitle').value.trim(),
            category:   document.getElementById('snippetEditorCategory').value.trim(),
            body:       body,
            sort_order: parseInt(document.getElementById('snippetEditorSortOrder').value || '0', 10),
        };

        const bodyText = (body || '').replace(/<[^>]+>/g, '').trim();
        if (!payload.title || !bodyText) {
            alert('Title and snippet text are required.');
            return;
        }

        const endpoint = id ? url('update', id) : url('create');
        try {
            const res = await fetch(endpoint, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken(),
                },
                body: JSON.stringify(payload),
            });
            if (!res.ok) {
                const err = await res.json();
                alert('Save failed: ' + (err.error || res.statusText));
                return;
            }
            poSnippetEditorModal()?.hide();
            await load();
        } catch (e) {
            alert('Network error while saving snippet.');
        }
    }

    async function deleteSnippet(id) {
        const snippet = _all.find(s => s.id === id);
        if (!snippet) return;
        if (!confirm(`Delete snippet "${snippet.title}"?\n\nThis cannot be undone.`)) return;

        try {
            const res = await fetch(url('delete', id), {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'X-CSRFToken': csrfToken() },
            });
            if (!res.ok) {
                alert('Delete failed.');
                return;
            }
            await load();
        } catch (e) {
            alert('Network error while deleting snippet.');
        }
    }

    function wireFilters() {
        const catSel = document.getElementById('snippetCategoryFilter');
        const searchInp = document.getElementById('snippetSearch');
        if (catSel) catSel.addEventListener('change', renderList);
        if (searchInp) searchInp.addEventListener('input', renderList);
    }

    function init() {
        wireFilters();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Wire Quill init to modal shown event (modal must be fully visible
    // before Quill can measure and mount into the container)
    (function wireQuillModalInit() {
        const modalEl = document.getElementById('snippetEditorModal');
        if (!modalEl) return;
        modalEl.addEventListener('shown.bs.modal', function () {
            const wasInitialized = !!_quill;
            _initQuill();
            // If Quill was just created for the first time, load pending content
            if (!wasInitialized && _quill) {
                const id = document.getElementById('snippetEditorId').value;
                if (id) {
                    const s = _all.find(x => x.id === parseInt(id, 10));
                    if (s) {
                        _quill.clipboard.dangerouslyPasteHTML(s.body || '');
                    }
                } else {
                    _quill.setContents([]);
                }
            }
        });
    })();

    return {
        load,
        copyPlain,
        copyHtml,
        openEditor,
        deleteSnippet,
        saveSnippet,
        renderList,
    };
})();

window._snippetRender = () => POSnippets.renderList();

function openPOSnippetsPanel() {
    const oc = poSnippetOffcanvas();
    if (!oc) return;
    oc.show();
    POSnippets.load();
}

function openSnippetEditor(id) {
    POSnippets.openEditor(id);
}

function saveSnippet() {
    POSnippets.saveSnippet();
}
