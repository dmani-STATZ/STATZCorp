(() => {
  const enrichBtn = document.getElementById('enrich-from-website-btn');
  const panel = document.getElementById('enrichment-panel');
  const rowsContainer = document.getElementById('enrichment-rows');
  const emptyMsg = document.getElementById('enrichment-empty-msg');
  if (!enrichBtn || !panel || !rowsContainer) return;

  // If the button is an anchor linking to the enrich page, don't bind AJAX here.
  if (enrichBtn.tagName === 'A') return;

  const supplierId = enrichBtn.dataset.supplierId;
  console.log("SupplierId =", supplierId);

  function getCSRF() {
    const name = 'csrftoken';
    const cookies = document.cookie ? document.cookie.split(';') : [];
    for (let c of cookies) {
      const cookie = c.trim();
      if (cookie.startsWith(name + '=')) {
        return decodeURIComponent(cookie.substring(name.length + 1));
      }
    }
    return '';
  }

  function renderRows(suggestions) {
    rowsContainer.innerHTML = '';
    let hasRows = false;
    const fields = {
      logo_url: 'Logo URL',
      primary_phone: 'Phone',
      primary_email: 'Email',
      address: 'Address',
    };
    Object.keys(fields).forEach((field) => {
      const data = suggestions[field];
      if (!data || !data.suggested) return;
      const suggestedList = Array.isArray(data.suggested) ? data.suggested : [data.suggested];
      hasRows = true;
      const row = document.createElement('div');
      row.className = 'enrichment-row border border-gray-200 rounded-md p-3 mb-2';
      row.dataset.field = field;

      // Choose control type
      let controlHtml = '';
      const inputType = field === 'address' ? 'textarea' : 'input';
      const initialValue = suggestedList[0] || '';

      if (suggestedList.length > 1) {
        controlHtml = `
          <label class="text-xs text-gray-600">Pick or edit:</label>
          <select class="suggested-select w-full border rounded px-2 py-1 text-sm mb-2">
            ${suggestedList.map((v) => `<option value="${v}">${v}</option>`).join('')}
          </select>
        `;
      }

      const entryControl =
        inputType === 'textarea'
          ? `<textarea class="suggested-input w-full border rounded px-2 py-1 text-sm" rows="2">${initialValue}</textarea>`
          : `<input class="suggested-input w-full border rounded px-2 py-1 text-sm" value="${initialValue}">`;

      row.innerHTML = `
        <strong>${fields[field]}</strong><br>
        <div class="text-sm text-gray-600">Current: <span class="current-value">${data.current || '—'}</span></div>
        <div class="text-sm text-gray-800 mb-2">Suggested:</div>
        ${controlHtml}
        ${entryControl}
        <button class="apply-suggestion-btn mt-2 inline-flex items-center px-2 py-1 bg-blue-600 text-white text-xs rounded">Apply</button>
      `;
      rowsContainer.appendChild(row);

      // If there is a select, sync to input
      const selectEl = row.querySelector('.suggested-select');
      const inputEl = row.querySelector('.suggested-input');
      if (selectEl && inputEl) {
        selectEl.addEventListener('change', () => {
          inputEl.value = selectEl.value;
        });
      }
    });
    emptyMsg.style.display = hasRows ? 'none' : 'block';
    panel.style.display = 'block';
    bindApply();
  }

  function bindApply() {
    rowsContainer.querySelectorAll('.apply-suggestion-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const row = btn.closest('.enrichment-row');
        const field = row.dataset.field;
        const input = row.querySelector('.suggested-input');
        const suggested = input ? input.value.trim() : '';
        fetch(`/suppliers/${supplierId}/apply-enrichment/`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRF(),
          },
          body: JSON.stringify({ field, value: suggested }),
        })
          .then((resp) => resp.json())
          .then(() => {
            row.querySelector('.current-value').textContent = suggested;
            row.classList.add('opacity-60');
          })
          .catch(() => {
            alert('Failed to apply suggestion');
          });
      });
    });
  }

  enrichBtn.addEventListener('click', () => {
    enrichBtn.disabled = true;
    panel.style.display = 'block';
    emptyMsg.textContent = 'Loading suggestions...';
    emptyMsg.style.display = 'block';
    fetch(`/suppliers/${supplierId}/enrich/`)
      .then((resp) => resp.json())
      .then((data) => {
        renderRows(data.suggestions || {});
      })
      .catch(() => {
        emptyMsg.textContent = 'No suggestions found.';
        panel.style.display = 'block';
      })
      .finally(() => {
        enrichBtn.disabled = false;
      });
  });
})();
