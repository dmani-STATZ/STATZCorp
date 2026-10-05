/* Supplier Research: loads each panel fragment independently. */
(function () {
  'use strict';

  var TIMEOUT_MS = 60000;
  var SPINNER_HTML =
    '<div class="text-center text-body-secondary py-3">' +
    '<div class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></div>' +
    'Loading…</div>';

  function showAlert(container, message, url) {
    container.textContent = '';
    var box = document.createElement('div');
    box.className = 'alert alert-danger d-flex flex-wrap align-items-center gap-3 mb-0';
    box.setAttribute('role', 'alert');
    var text = document.createElement('span');
    text.textContent = message;
    box.appendChild(text);
    if (url) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-outline-secondary btn-sm';
      btn.setAttribute('data-panel-reload', url);
      btn.textContent = 'Retry';
      box.appendChild(btn);
    }
    container.appendChild(box);
  }

  function loadPanel(container, url) {
    container.innerHTML = SPINNER_HTML;
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, TIMEOUT_MS);

    return fetch(url, {
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      signal: controller.signal
    })
      .then(function (response) {
        // A login / permission-denied page arrives as a redirect or non-2xx;
        // never inject it into the card.
        if (response.redirected || !response.ok) {
          showAlert(container, 'Your session expired or you don’t have access — reload the page.', null);
          return null;
        }
        return response.text();
      })
      .then(function (html) {
        if (html !== null && html !== undefined) {
          container.innerHTML = html;
        }
      })
      .catch(function (err) {
        var msg = err && err.name === 'AbortError'
          ? 'This section took too long to load.'
          : 'This section failed to load.';
        showAlert(container, msg, url);
      })
      .then(function () { clearTimeout(timer); });
  }

  function init() {
    var containers = document.querySelectorAll('[data-panel-url]');
    Array.prototype.forEach.call(containers, function (container) {
      loadPanel(container, container.getAttribute('data-panel-url'));
    });
  }

  document.addEventListener('click', function (event) {
    var reload = event.target.closest('[data-panel-reload]');
    if (reload) {
      var container = reload.closest('[data-panel-url]');
      if (container) {
        loadPanel(container, reload.getAttribute('data-panel-reload'));
      }
      return;
    }
    var toggle = event.target.closest('[data-show-all]');
    if (toggle) {
      var root = toggle.closest('[data-panel-url]');
      if (root) {
        Array.prototype.forEach.call(root.querySelectorAll('[data-extra-row]'), function (row) {
          row.classList.remove('d-none');
        });
      }
      toggle.remove();
    }
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
