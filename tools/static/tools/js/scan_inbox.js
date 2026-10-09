(function () {
    "use strict";

    const root = document.getElementById("scan-inbox-app");
    if (!root) return;

    const urls = {
        items: root.dataset.itemsUrl,
        pdf: root.dataset.pdfUrl,
        search: root.dataset.searchUrl,
        destination: root.dataset.destinationUrl,
        file: root.dataset.fileUrl,
        skip: root.dataset.skipUrl,
    };
    const writesEnabled = root.dataset.writesEnabled === "1";

    const els = {
        refresh: document.getElementById("scan-inbox-refresh"),
        count: document.getElementById("scan-inbox-count"),
        itemsList: document.getElementById("scan-inbox-items-list"),
        problemsList: document.getElementById("scan-inbox-problems-list"),
        preview: document.getElementById("scan-inbox-preview"),
        previewEmpty: document.getElementById("scan-inbox-preview-empty"),
        search: document.getElementById("scan-inbox-search"),
        searchResults: document.getElementById("scan-inbox-search-results"),
        destination: document.getElementById("scan-inbox-destination"),
        filename: document.getElementById("scan-inbox-filename"),
        panelError: document.getElementById("scan-inbox-panel-error"),
        fileBtn: document.getElementById("scan-inbox-file-btn"),
        skipBtn: document.getElementById("scan-inbox-skip-btn"),
        skipReason: document.getElementById("scan-inbox-skip-reason"),
        skipOther: document.getElementById("scan-inbox-skip-other"),
    };

    let items = [];
    let problems = [];
    let selectedKey = null;
    let selectedContract = null;
    let destination = null;
    let destinationLoading = false;
    let searchResults = [];
    let busy = false;
    let searchTimer = null;

    const BLOCKING_DESTINATION_KINDS = new Set([
        "stored_missing",
        "duplicates",
        "invalid",
        "error",
    ]);

    els.refresh.addEventListener("click", () => loadItems());
    els.search.addEventListener("input", onSearchInput);
    els.search.addEventListener("keydown", onSearchKeydown);
    els.fileBtn.addEventListener("click", () => fileSelected());
    els.skipBtn.addEventListener("click", () => skipSelectedPdf());
    els.skipReason.addEventListener("change", toggleSkipOther);
    document.addEventListener("keydown", onGlobalKeydown);

    toggleSkipOther();
    loadItems();

    function itemKey(item) {
        return `${item.message_id}\0${item.attachment_name}`;
    }

    function getSelectedItem() {
        if (!selectedKey) return null;
        return items.find((row) => itemKey(row) === selectedKey) || null;
    }

    function setBusy(next) {
        busy = next;
        updateActionButtons();
    }

    function clearPanelError() {
        els.panelError.textContent = "";
        els.panelError.classList.add("d-none");
    }

    function showPanelError(message) {
        els.panelError.textContent = message;
        els.panelError.classList.remove("d-none");
    }

    function getCsrfToken() {
        const name = "csrftoken";
        const cookies = document.cookie ? document.cookie.split("; ") : [];
        for (const cookie of cookies) {
            const eq = cookie.indexOf("=");
            if (eq === -1) continue;
            const key = cookie.slice(0, eq);
            const value = cookie.slice(eq + 1);
            if (key === name) return decodeURIComponent(value);
        }
        return "";
    }

    async function loadItems() {
        clearPanelError();
        setBusy(true);
        try {
            const resp = await fetch(urls.items, { credentials: "same-origin" });
            if (!resp.ok) throw new Error("Could not load inbox items.");
            const data = await resp.json();
            items = data.items || [];
            problems = data.problems || [];
            renderItems();
            renderProblems();
            if (data.error) {
                showPanelError(String(data.error));
            }
            if (!getSelectedItem()) {
                selectedKey = items.length ? itemKey(items[0]) : null;
            }
            updatePreview();
            updateFilenamePreview();
            updateActionButtons();
        } catch (err) {
            showPanelError(err.message || "Could not load inbox items.");
        } finally {
            setBusy(false);
        }
    }

    function renderItems() {
        els.itemsList.replaceChildren();
        els.count.textContent = String(items.length);
        if (!items.length) {
            const empty = document.createElement("div");
            empty.className = "px-3 py-3 small text-muted";
            empty.textContent = "No pending PDFs.";
            els.itemsList.appendChild(empty);
            return;
        }
        items.forEach((item) => {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "scan-inbox-item-btn w-100 text-start border-0 border-bottom px-3 py-2";
            if (itemKey(item) === selectedKey) {
                btn.classList.add("scan-inbox-item-selected");
            }

            const top = document.createElement("div");
            top.className = "d-flex justify-content-between align-items-start gap-2";
            const name = document.createElement("span");
            name.className = "fw-medium text-truncate";
            name.textContent = item.attachment_name || "(unnamed)";
            top.appendChild(name);
            if (item.sibling_count > 1) {
                const badge = document.createElement("span");
                badge.className = "badge bg-secondary flex-shrink-0";
                badge.textContent = `${item.sibling_index} of ${item.sibling_count}`;
                top.appendChild(badge);
            }

            const meta = document.createElement("div");
            meta.className = "small text-muted";
            meta.textContent = `${formatReceived(item.received_at)} · ${formatKb(item.size)}`;

            btn.appendChild(top);
            btn.appendChild(meta);
            btn.addEventListener("click", () => {
                selectedKey = itemKey(item);
                renderItems();
                updatePreview();
                updateFilenamePreview();
                clearPanelError();
                updateActionButtons();
            });
            els.itemsList.appendChild(btn);
        });
    }

    function renderProblems() {
        els.problemsList.replaceChildren();
        if (!problems.length) {
            const none = document.createElement("div");
            none.className = "text-muted";
            none.textContent = "None.";
            els.problemsList.appendChild(none);
            return;
        }
        problems.forEach((prob) => {
            const row = document.createElement("div");
            row.className = "scan-inbox-problem-row mb-2 pb-2 border-bottom";

            const subject = document.createElement("div");
            subject.className = "text-truncate";
            subject.textContent = prob.subject || "(no subject)";
            row.appendChild(subject);

            const actions = document.createElement("div");
            actions.className = "mt-1";
            const skipBtn = document.createElement("button");
            skipBtn.type = "button";
            skipBtn.className = "btn btn-outline-secondary btn-sm";
            skipBtn.textContent = "Skip";
            skipBtn.disabled = busy;
            skipBtn.addEventListener("click", () => skipProblem(prob, skipBtn));
            actions.appendChild(skipBtn);
            row.appendChild(actions);
            els.problemsList.appendChild(row);
        });
    }

    function updatePreview() {
        const item = getSelectedItem();
        if (!item) {
            els.preview.src = "about:blank";
            els.preview.classList.add("d-none");
            els.previewEmpty.classList.remove("d-none");
            return;
        }
        const params = new URLSearchParams({
            message_id: item.message_id,
            attachment_id: item.attachment_id,
        });
        els.preview.src = `${urls.pdf}?${params.toString()}`;
        els.preview.classList.remove("d-none");
        els.previewEmpty.classList.add("d-none");
    }

    function onSearchInput() {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(runSearch, 300);
    }

    async function runSearch() {
        const q = (els.search.value || "").trim();
        searchResults = [];
        renderSearchResults();
        if (q.length < 3) {
            selectedContract = null;
            destination = null;
            renderDestination();
            updateFilenamePreview();
            updateActionButtons();
            return;
        }
        try {
            const params = new URLSearchParams({ q });
            const resp = await fetch(`${urls.search}?${params.toString()}`, {
                credentials: "same-origin",
            });
            if (!resp.ok) throw new Error("Search failed.");
            searchResults = await resp.json();
            renderSearchResults();
        } catch (err) {
            showPanelError(err.message || "Search failed.");
        }
    }

    function renderSearchResults() {
        els.searchResults.replaceChildren();
        if (!searchResults.length) {
            const empty = document.createElement("div");
            empty.className = "small text-muted";
            empty.textContent =
                (els.search.value || "").trim().length >= 3
                    ? "No matches."
                    : "Type at least 3 characters.";
            els.searchResults.appendChild(empty);
            return;
        }
        searchResults.forEach((row, index) => {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "scan-inbox-search-btn w-100 text-start border rounded px-2 py-2 mb-1";
            if (selectedContract && selectedContract.id === row.id) {
                btn.classList.add("scan-inbox-item-selected");
            }

            const line = document.createElement("div");
            line.className = "d-flex justify-content-between align-items-center gap-2";
            const left = document.createElement("span");
            left.textContent = `${row.contract_number || ""}${
                row.po_number ? ` · PO ${row.po_number}` : ""
            }`;
            const badge = document.createElement("span");
            badge.className = `badge ${statusBadgeClass(row.status__description)}`;
            badge.textContent = row.status__description || "—";
            line.appendChild(left);
            line.appendChild(badge);
            btn.appendChild(line);

            btn.addEventListener("click", () => selectContract(row));
            btn.dataset.index = String(index);
            els.searchResults.appendChild(btn);
        });
    }

    function statusBadgeClass(status) {
        const s = (status || "").toLowerCase();
        if (s === "open") return "bg-success";
        if (s === "closed") return "bg-secondary";
        if (s === "canceled") return "bg-danger";
        return "bg-secondary";
    }

    async function selectContract(row) {
        clearPanelError();
        selectedContract = row;
        destination = null;
        destinationLoading = true;
        renderSearchResults();
        renderDestination();
        updateFilenamePreview();
        updateActionButtons();
        try {
            const params = new URLSearchParams({ contract_id: String(row.id) });
            const resp = await fetch(`${urls.destination}?${params.toString()}`, {
                credentials: "same-origin",
            });
            if (!resp.ok) {
                throw new Error("Could not resolve destination.");
            }
            destination = await resp.json();
            renderDestination();
            updateActionButtons();
        } catch (err) {
            showPanelError(err.message || "Could not resolve destination.");
        } finally {
            destinationLoading = false;
            renderDestination();
            updateActionButtons();
        }
    }

    function renderDestination() {
        els.destination.replaceChildren();
        if (!selectedContract) {
            return;
        }
        if (!destination) {
            const loading = document.createElement("div");
            loading.className = "text-muted";
            loading.textContent = destinationLoading
                ? "Checking folder…"
                : "Select a contract to see the folder.";
            els.destination.appendChild(loading);
            return;
        }
        const kind = destination.kind || "";
        const line = document.createElement("div");
        if (kind === "existing" || kind === "snapshot") {
            line.className = "text-success";
            line.textContent = `Files into: ${destination.path || ""}`;
        } else if (kind === "create") {
            line.className = "text-primary";
            line.textContent = `Will create: ${destination.create_path || ""}`;
        } else {
            line.className = "text-danger";
            line.textContent = destination.message || kind || "Cannot file to this contract.";
        }
        els.destination.appendChild(line);
    }

    function canFile() {
        if (!writesEnabled || busy) return false;
        const item = getSelectedItem();
        if (!item || !selectedContract) return false;
        if (destination && BLOCKING_DESTINATION_KINDS.has(destination.kind || "")) {
            return false;
        }
        return true;
    }

    function updateFilenamePreview() {
        const item = getSelectedItem();
        if (!item || !selectedContract) {
            els.filename.textContent = "";
            return;
        }
        const cn = selectedContract.contract_number || "";
        const stamp = item.name_stamp || "";
        els.filename.textContent = `Target filename: Completed - ${cn} - ${stamp}.pdf`;
    }

    function updateActionButtons() {
        const hasItem = !!getSelectedItem();
        els.skipBtn.disabled = busy || !hasItem;
        els.fileBtn.disabled = !canFile();
        renderProblems();
    }

    function resolveSkipReason() {
        const choice = els.skipReason.value;
        if (choice === "Other") {
            return (els.skipOther.value || "").trim();
        }
        return choice;
    }

    function toggleSkipOther() {
        const show = els.skipReason.value === "Other";
        els.skipOther.classList.toggle("d-none", !show);
    }

    async function fileSelected() {
        if (!canFile()) return;
        const item = getSelectedItem();
        clearPanelError();
        setBusy(true);
        try {
            const body = new FormData();
            body.append("message_id", item.message_id);
            body.append("attachment_name", item.attachment_name);
            body.append("contract_id", String(selectedContract.id));
            const resp = await fetch(urls.file, {
                method: "POST",
                headers: { "X-CSRFToken": getCsrfToken() },
                body,
                credentials: "same-origin",
            });
            const data = await parseJson(resp);
            if (!data.ok) {
                throw new Error(data.error || "File failed.");
            }
            removeCurrentItem(item);
        } catch (err) {
            showPanelError(err.message || "File failed.");
        } finally {
            setBusy(false);
        }
    }

    async function skipSelectedPdf() {
        const item = getSelectedItem();
        if (!item || busy) return;
        clearPanelError();
        setBusy(true);
        try {
            const reason = resolveSkipReason();
            const body = new FormData();
            body.append("message_id", item.message_id);
            body.append("attachment_name", item.attachment_name);
            body.append("reason", reason);
            const resp = await fetch(urls.skip, {
                method: "POST",
                headers: { "X-CSRFToken": getCsrfToken() },
                body,
                credentials: "same-origin",
            });
            const data = await parseJson(resp);
            if (!data.ok) {
                throw new Error(data.error || "Skip failed.");
            }
            removeCurrentItem(item);
        } catch (err) {
            showPanelError(err.message || "Skip failed.");
        } finally {
            setBusy(false);
        }
    }

    async function skipProblem(prob, btn) {
        if (busy) return;
        clearPanelError();
        setBusy(true);
        btn.disabled = true;
        try {
            const body = new FormData();
            body.append("message_id", prob.message_id);
            body.append("attachment_name", "");
            body.append("reason", "No PDF attachment");
            const resp = await fetch(urls.skip, {
                method: "POST",
                headers: { "X-CSRFToken": getCsrfToken() },
                body,
                credentials: "same-origin",
            });
            const data = await parseJson(resp);
            if (!data.ok) {
                throw new Error(data.error || "Skip failed.");
            }
            problems = problems.filter((p) => p.message_id !== prob.message_id);
            renderProblems();
        } catch (err) {
            showPanelError(err.message || "Skip failed.");
        } finally {
            setBusy(false);
        }
    }

    function removeCurrentItem(removed) {
        const prevMessageId = removed.message_id;
        const keepContract = selectedContract;
        const idx = items.findIndex((row) => itemKey(row) === itemKey(removed));
        if (idx !== -1) {
            items.splice(idx, 1);
        }
        problems = problems.filter((p) => p.message_id !== removed.message_id || removed.attachment_name);

        let next = items[idx] || items[idx - 1] || null;
        selectedKey = next ? itemKey(next) : null;

        if (next && keepContract && next.message_id === prevMessageId) {
            selectedContract = keepContract;
        } else if (next && next.message_id !== prevMessageId) {
            selectedContract = null;
            destination = null;
        }

        renderItems();
        renderProblems();
        renderSearchResults();
        renderDestination();
        updatePreview();
        updateFilenamePreview();
        updateActionButtons();

        if (selectedContract && next && next.message_id === prevMessageId && !destination) {
            selectContract(selectedContract);
        }
    }

    function onSearchKeydown(event) {
        if (event.key !== "Enter") return;
        event.preventDefault();
        if (!searchResults.length) return;
        selectContract(searchResults[0]);
    }

    function onGlobalKeydown(event) {
        if (!event.ctrlKey || event.key !== "Enter") return;
        if (document.activeElement === els.search) return;
        if (!canFile()) return;
        event.preventDefault();
        fileSelected();
    }

    async function parseJson(resp) {
        try {
            return await resp.json();
        } catch (_) {
            return { ok: false, error: `Request failed (${resp.status}).` };
        }
    }

    function formatReceived(value) {
        if (!value) return "—";
        const d = new Date(value);
        if (Number.isNaN(d.getTime())) return String(value);
        return d.toLocaleString();
    }

    function formatKb(bytes) {
        const n = Number(bytes) || 0;
        return `${Math.max(1, Math.round(n / 1024))} KB`;
    }
})();
