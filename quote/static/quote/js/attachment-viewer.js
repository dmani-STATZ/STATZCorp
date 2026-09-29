/*
 * Split-screen attachment viewer for the Phase 2 mailbox.
 *
 *   QuoteAttachmentViewer.init(root, opts)
 *
 * `root` is the message fragment (.quote-msg). Every `[data-view-attachment]` button in it opens
 * its file (a PDF or image, served by quote:attachment_view) in a panel beside the message body
 * instead of a new browser tab. The panel is resizable (drag or arrow keys on the divider), stacks
 * under the message when there is no room, and remembers two things per browser: its width, and
 * whether the rep had it open, so it comes back as they move from message to message.
 *
 * opts.onToggle(isOpen) lets the page react (the mailbox hides its inbox list while the viewer and
 * the quote drawer are both open).
 */
(function () {
  'use strict';

  const WIDTH_KEY = 'quoteViewerWidth';
  const OPEN_KEY = 'quoteViewerOpen';
  const MIN_PANE = 280;        // neither side may be dragged narrower than this
  const STACK_BELOW = 760;     // container width under which the viewer goes below the message

  function storeGet(key) { try { return window.localStorage.getItem(key); } catch (e) { return null; } }
  function storeSet(key, value) { try { window.localStorage.setItem(key, value); } catch (e) { /* ignore */ } }
  function storeDrop(key) { try { window.localStorage.removeItem(key); } catch (e) { /* ignore */ } }

  function init(root, opts) {
    opts = opts || {};
    const buttons = Array.from(root.querySelectorAll('[data-view-attachment]'));
    const split = root.querySelector('#qSplit');
    if (!split) return null;
    const viewer = split.querySelector('#qViewer');
    const handle = split.querySelector('#qSplitHandle');
    const body = split.querySelector('#qViewerBody');
    const tabs = split.querySelector('#qViewerTabs');
    const pop = split.querySelector('#qViewerPop');
    let current = null;

    function clampWidth(px) {
      const total = split.getBoundingClientRect().width;
      return Math.max(MIN_PANE, Math.min(px, total - MIN_PANE));
    }
    function applyWidth(px) {
      viewer.style.flexBasis = clampWidth(px) + 'px';
    }
    function isStacked() { return split.classList.contains('stacked'); }
    function checkStacking() {
      split.classList.toggle('stacked', split.getBoundingClientRect().width < STACK_BELOW);
    }

    function render(btn) {
      body.textContent = '';
      const url = btn.dataset.viewUrl;
      if (btn.dataset.viewKind === 'image') {
        const wrap = document.createElement('div');
        wrap.className = 'quote-viewer-image';
        const img = document.createElement('img');
        img.src = url;
        img.alt = btn.dataset.viewName;
        wrap.appendChild(img);
        body.appendChild(wrap);
      } else {
        // No `sandbox` attribute on purpose: browsers will not run their PDF viewer inside a sandboxed
        // frame. The response is a verified PDF served `nosniff` with a no-load CSP.
        const frame = document.createElement('iframe');
        frame.className = 'quote-viewer-frame';
        // Open parameters for the browser's PDF viewer: no thumbnail sidebar (the panel is narrow),
        // page fitted to the width.
        frame.src = url + '#navpanes=0&view=FitH';
        frame.title = btn.dataset.viewName;
        body.appendChild(frame);
      }
      pop.href = btn.dataset.openUrl;
      tabs.querySelectorAll('button').forEach(t => t.classList.toggle('active', t.dataset.for === btn.dataset.viewAttachment));
    }

    function open(btn, remember) {
      if (viewer.classList.contains('d-none')) {
        viewer.classList.remove('d-none');
        if (!isStacked()) handle.classList.remove('d-none');
        split.classList.add('has-viewer');
        const saved = parseInt(storeGet(WIDTH_KEY), 10);
        if (isStacked()) viewer.style.flexBasis = '';      // stacked: height comes from the CSS
        else applyWidth(Number.isFinite(saved) ? saved : split.getBoundingClientRect().width / 2);
      }
      current = btn;
      render(btn);
      if (remember) storeSet(OPEN_KEY, '1');
      if (opts.onToggle) opts.onToggle(true);
    }

    function close(remember) {
      viewer.classList.add('d-none');
      handle.classList.add('d-none');
      split.classList.remove('has-viewer');
      body.textContent = '';     // stop loading / drop the document
      current = null;
      if (remember) storeDrop(OPEN_KEY);
      if (opts.onToggle) opts.onToggle(false);
    }

    // One tab per previewable attachment so a message with several can flip between them.
    tabs.textContent = '';
    buttons.forEach(btn => {
      const tab = document.createElement('button');
      tab.type = 'button';
      tab.className = 'quote-viewer-tab';
      tab.dataset.for = btn.dataset.viewAttachment;
      tab.title = btn.dataset.viewName;
      tab.textContent = btn.dataset.viewName;
      tab.addEventListener('click', () => open(btn, true));
      tabs.appendChild(tab);
    });

    buttons.forEach(btn => btn.addEventListener('click', () => open(btn, true)));
    root.querySelector('#qViewerClose').addEventListener('click', () => close(true));
    if (typeof ResizeObserver !== 'undefined') {
      new ResizeObserver(() => {
        checkStacking();
        if (!viewer.classList.contains('d-none')) {
          handle.classList.toggle('d-none', isStacked());
          if (isStacked()) {
            viewer.style.flexBasis = '';
          } else {
            const saved = parseInt(storeGet(WIDTH_KEY), 10);
            applyWidth(Number.isFinite(saved) ? saved : split.getBoundingClientRect().width / 2);
          }
        }
      }).observe(split);
    }
    checkStacking();

    // ── Drag / keyboard resize ───────────────────────────────────────────
    let dragging = false;
    handle.addEventListener('pointerdown', e => {
      dragging = true;
      handle.setPointerCapture(e.pointerId);
      split.classList.add('dragging');
      e.preventDefault();
    });
    handle.addEventListener('pointermove', e => {
      if (!dragging) return;
      applyWidth(split.getBoundingClientRect().right - e.clientX);
    });
    function endDrag(e) {
      if (!dragging) return;
      dragging = false;
      split.classList.remove('dragging');
      try { handle.releasePointerCapture(e.pointerId); } catch (err) { /* already released */ }
      storeSet(WIDTH_KEY, String(Math.round(viewer.getBoundingClientRect().width)));
    }
    handle.addEventListener('pointerup', endDrag);
    handle.addEventListener('pointercancel', endDrag);
    handle.addEventListener('keydown', e => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault();
      const now = viewer.getBoundingClientRect().width;
      applyWidth(now + (e.key === 'ArrowLeft' ? 32 : -32));
      storeSet(WIDTH_KEY, String(Math.round(viewer.getBoundingClientRect().width)));
    });

    // Came back to the mailbox with the viewer open last time: open it on this message's first file.
    if (buttons.length && storeGet(OPEN_KEY) === '1') open(buttons[0], false);

    return { open: open, close: close, current: () => current };
  }

  window.QuoteAttachmentViewer = { init: init };
})();
