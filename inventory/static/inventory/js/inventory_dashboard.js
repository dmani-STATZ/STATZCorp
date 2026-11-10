(function () {
    'use strict';

    var SEARCH_DEBOUNCE_MS = 300;

    function initFilters() {
        var form = document.getElementById('invFilterForm');
        if (!form) return;
        var search = document.getElementById('invSearch');
        var timer = null;

        form.querySelectorAll('select[data-inv-autosubmit]').forEach(function (select) {
            select.addEventListener('change', function () { form.requestSubmit(); });
        });

        if (search) {
            var initial = search.value;
            search.addEventListener('input', function () {
                clearTimeout(timer);
                timer = setTimeout(function () {
                    if (search.value.trim() !== initial.trim()) form.requestSubmit();
                }, SEARCH_DEBOUNCE_MS);
            });
            if (initial) {
                search.focus();
                search.setSelectionRange(initial.length, initial.length);
            }
        }
    }

    function initDelete() {
        var modalEl = document.getElementById('invDeleteModal');
        if (!modalEl || !window.bootstrap) return;
        var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        var nameEl = modalEl.querySelector('[data-inv-delete-name]');
        var errorEl = modalEl.querySelector('[data-inv-delete-error]');
        var confirmBtn = modalEl.querySelector('[data-inv-delete-confirm]');
        var csrfInput = modalEl.querySelector('input[name="csrfmiddlewaretoken"]');
        var deleteUrl = null;

        document.addEventListener('click', function (event) {
            var trigger = event.target.closest('[data-inv-delete-url]');
            if (!trigger) return;
            deleteUrl = trigger.getAttribute('data-inv-delete-url');
            nameEl.textContent = trigger.getAttribute('data-inv-delete-label') || 'this item';
            errorEl.classList.add('d-none');
            confirmBtn.disabled = false;
            modal.show();
        });

        confirmBtn.addEventListener('click', function () {
            if (!deleteUrl) return;
            confirmBtn.disabled = true;
            errorEl.classList.add('d-none');
            fetch(deleteUrl, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfInput ? csrfInput.value : '' },
                credentials: 'same-origin'
            })
                .then(function (response) {
                    if (!response.ok) throw new Error('HTTP ' + response.status);
                    return response.json();
                })
                .then(function (data) {
                    if (!data.success) throw new Error('Delete rejected');
                    window.location.reload();
                })
                .catch(function () {
                    errorEl.classList.remove('d-none');
                    confirmBtn.disabled = false;
                });
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        initFilters();
        initDelete();
    });
})();
