/* CLIN shipments popup. Reloads itself after each successful write. */
(function () {
    var root = document.getElementById("clin-ship-popup");
    if (!root) {
        return;
    }

    var clinId = root.getAttribute("data-clin-id");
    var addUrl = root.getAttribute("data-add-url");
    var autoCalcUrl = root.getAttribute("data-auto-calc-url");
    var clinUom = root.getAttribute("data-clin-uom") || "";
    var autoCalcTimer = null;
    var autoCalcToken = 0;
    var mode = "add";
    var editingRow = null;
    var saveInFlight = false;
    var modalEl = document.getElementById("shipmentModal");
    var modal = modalEl && window.bootstrap ? new window.bootstrap.Modal(modalEl) : null;
    var saveBtn = document.getElementById("shipment-modal-save");

    function csrfToken() {
        var input = document.querySelector("[name=csrfmiddlewaretoken]");
        return input ? input.value : "";
    }

    function showAlert(message) {
        var el = document.getElementById("popup-alert");
        if (!el) {
            return;
        }
        el.textContent = message || "Something went wrong.";
        el.classList.remove("d-none");
    }

    function clearAlert() {
        var el = document.getElementById("popup-alert");
        if (!el) {
            return;
        }
        el.textContent = "";
        el.classList.add("d-none");
    }

    function showModalAlert(message) {
        var el = document.getElementById("shipment-modal-alert");
        if (!el) {
            return;
        }
        el.textContent = message || "Something went wrong.";
        el.classList.remove("d-none");
    }

    function clearModalAlert() {
        var el = document.getElementById("shipment-modal-alert");
        if (!el) {
            return;
        }
        el.textContent = "";
        el.classList.add("d-none");
    }

    function notifyOpener(id) {
        if (
            window.opener &&
            !window.opener.closed &&
            typeof window.opener.onClinShipmentsChanged === "function"
        ) {
            window.opener.onClinShipmentsChanged(id);
        }
    }

    function finishSuccess() {
        if (modal) {
            modal.hide();
        }
        notifyOpener(clinId);
        window.location.reload();
    }

    function localToday() {
        var now = new Date();
        var month = String(now.getMonth() + 1).padStart(2, "0");
        var day = String(now.getDate()).padStart(2, "0");
        return now.getFullYear() + "-" + month + "-" + day;
    }

    function postJson(url, payload) {
        return fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": csrfToken(),
            },
            body: JSON.stringify(payload),
        }).then(function (response) {
            return response.json().then(
                function (data) {
                    return { ok: response.ok, status: response.status, data: data };
                },
                function () {
                    return { ok: false, status: response.status, data: {} };
                }
            );
        });
    }

    function qtyValue(raw) {
        var value = String(raw || "").trim();
        if (!value) {
            return { error: "Qty is required." };
        }
        if (!/^-?\d+(\.\d+)?$/.test(value)) {
            return { error: "Qty must be a number." };
        }
        return { value: value };
    }

    function optionalMoney(raw) {
        var value = String(raw || "").trim();
        if (!value) {
            return { skip: true };
        }
        if (!/^-?\d+(\.\d+)?$/.test(value)) {
            return { error: "Paid and Customer Pay must be numbers." };
        }
        return { value: value };
    }

    function setPreviews(quoteText, itemText) {
        var quote = document.getElementById("popup-preview-quote");
        var item = document.getElementById("popup-preview-item");
        if (quote) {
            quote.value = quoteText;
        }
        if (item) {
            item.value = itemText;
        }
    }

    function fieldInput(scope, name) {
        if (!scope) {
            return null;
        }
        return scope.querySelector('[data-field="' + name + '"]');
    }

    function fieldValue(scope, name) {
        var el = fieldInput(scope, name);
        return el ? el.value : "";
    }

    function setField(scope, name, value) {
        var el = fieldInput(scope, name);
        if (el) {
            el.value = value == null ? "" : value;
        }
    }

    function scheduleAutoCalc() {
        var qtyRaw = String(fieldValue(modalEl, "ship_qty") || "").trim();
        if (autoCalcTimer) {
            window.clearTimeout(autoCalcTimer);
            autoCalcTimer = null;
        }
        if (!qtyRaw || Number(qtyRaw) === 0 || !/^-?\d+(\.\d+)?$/.test(qtyRaw)) {
            autoCalcToken += 1;
            setPreviews("—", "—");
            return;
        }
        autoCalcTimer = window.setTimeout(function () {
            var token = ++autoCalcToken;
            var url = autoCalcUrl
                + "?clin_id=" + encodeURIComponent(clinId)
                + "&ship_qty=" + encodeURIComponent(qtyRaw);
            fetch(url, { credentials: "same-origin" })
                .then(function (response) {
                    return response.json();
                })
                .then(function (data) {
                    if (token !== autoCalcToken) {
                        return;
                    }
                    if (!data || !data.success) {
                        setPreviews("—", "—");
                        return;
                    }
                    setPreviews(
                        Number(data.auto_quote_value).toFixed(2),
                        Number(data.auto_item_value).toFixed(2)
                    );
                })
                .catch(function () {
                    if (token === autoCalcToken) {
                        setPreviews("—", "—");
                    }
                });
        }, 300);
    }

    function setMode(next) {
        mode = next;
        var addOnly = document.querySelectorAll("#shipmentModal .js-add-only");
        var editOnly = document.querySelectorAll("#shipmentModal .js-edit-only");
        addOnly.forEach(function (el) {
            el.classList.toggle("d-none", next !== "add");
        });
        editOnly.forEach(function (el) {
            el.classList.toggle("d-none", next !== "edit");
        });
        var title = document.getElementById("shipmentModalLabel");
        if (title) {
            title.textContent = next === "edit" ? "Edit Shipment" : "Add Shipment";
        }
    }

    function clearForm() {
        ["name", "ship_date", "ship_qty", "uom", "pod_date", "comments", "paid_amount", "wawf_payment"].forEach(function (name) {
            setField(modalEl, name, "");
        });
        setPreviews("—", "—");
        clearModalAlert();
    }

    function blankToNull(raw) {
        var value = String(raw || "").trim();
        return value ? value : null;
    }

    function readLogistics() {
        var qty = qtyValue(fieldValue(modalEl, "ship_qty"));
        if (qty.error) {
            return qty;
        }
        return {
            value: {
                name: blankToNull(fieldValue(modalEl, "name")),
                ship_date: blankToNull(fieldValue(modalEl, "ship_date")),
                ship_qty: qty.value,
                uom: String(fieldValue(modalEl, "uom") || "").trim(),
                comments: fieldValue(modalEl, "comments") || "",
                pod_date: blankToNull(fieldValue(modalEl, "pod_date")),
            },
        };
    }

    function openModal() {
        if (!modal) {
            return;
        }
        modal.show();
    }

    function openAdd() {
        editingRow = null;
        clearForm();
        setMode("add");
        setField(modalEl, "uom", clinUom);
        openModal();
    }

    function openEdit(row) {
        if (!row) {
            return;
        }
        editingRow = row;
        clearForm();
        setMode("edit");
        setField(modalEl, "name", row.getAttribute("data-name") || "");
        setField(modalEl, "ship_date", row.getAttribute("data-ship-date") || "");
        setField(modalEl, "ship_qty", row.getAttribute("data-ship-qty") || "");
        setField(modalEl, "uom", row.getAttribute("data-uom") || "");
        setField(modalEl, "comments", row.getAttribute("data-comments") || "");
        setField(modalEl, "pod_date", row.getAttribute("data-pod-date") || "");
        openModal();
    }

    function setSaveDisabled(disabled) {
        saveInFlight = disabled;
        if (saveBtn) {
            saveBtn.disabled = disabled;
        }
    }

    function submitModal() {
        if (saveInFlight) {
            return;
        }
        clearModalAlert();
        var parsed = readLogistics();
        if (parsed.error) {
            showModalAlert(parsed.error);
            return;
        }
        var url;
        var payload;
        if (mode === "edit") {
            if (!editingRow) {
                showModalAlert("Could not save the shipment.");
                return;
            }
            url = editingRow.getAttribute("data-update-url");
            payload = {
                name: parsed.value.name,
                ship_qty: parsed.value.ship_qty,
                uom: parsed.value.uom,
                ship_date: parsed.value.ship_date,
                comments: parsed.value.comments,
                pod_date: parsed.value.pod_date || "",
            };
        } else {
            var paid = optionalMoney(fieldValue(modalEl, "paid_amount"));
            if (paid.error) {
                showModalAlert(paid.error);
                return;
            }
            var customerPay = optionalMoney(fieldValue(modalEl, "wawf_payment"));
            if (customerPay.error) {
                showModalAlert(customerPay.error);
                return;
            }
            url = addUrl;
            payload = {
                clin_id: clinId,
                name: parsed.value.name,
                ship_qty: parsed.value.ship_qty,
                uom: parsed.value.uom,
                ship_date: parsed.value.ship_date,
                comments: parsed.value.comments,
                pod_date: parsed.value.pod_date,
            };
            if (!paid.skip) {
                payload.paid_amount = paid.value;
            }
            if (!customerPay.skip) {
                payload.wawf_payment = customerPay.value;
            }
        }
        setSaveDisabled(true);
        postJson(url, payload).then(function (result) {
            if (!result.ok || !result.data.success) {
                showModalAlert((result.data && result.data.error) || "Could not save the shipment.");
                setSaveDisabled(false);
                return;
            }
            finishSuccess();
        }).catch(function () {
            showModalAlert("Could not save the shipment.");
            setSaveDisabled(false);
        });
    }

    function stripOpenParams() {
        if (!window.history || typeof window.history.replaceState !== "function") {
            return;
        }
        var url = new URL(window.location.href);
        if (!url.searchParams.has("add") && !url.searchParams.has("edit")) {
            return;
        }
        url.searchParams.delete("add");
        url.searchParams.delete("edit");
        window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
    }

    var qtyInput = document.getElementById("shipment-qty");
    if (qtyInput) {
        qtyInput.addEventListener("input", function () {
            if (mode === "add") {
                scheduleAutoCalc();
            }
        });
    }

    document.addEventListener("click", function (event) {
        var todayBtn = event.target.closest(".js-today");
        if (todayBtn) {
            var wrap = todayBtn.parentElement;
            var input = wrap ? wrap.querySelector('input[type="date"]') : null;
            if (input) {
                input.value = localToday();
            }
            return;
        }

        if (event.target.closest("#open-add-shipment")) {
            openAdd();
            return;
        }

        if (event.target.closest("#shipment-modal-save")) {
            submitModal();
            return;
        }

        var editBtn = event.target.closest(".js-edit-shipment");
        if (editBtn) {
            openEdit(editBtn.closest("tr[data-shipment-id]"));
            return;
        }

        var deleteBtn = event.target.closest(".js-delete-shipment");
        if (!deleteBtn) {
            return;
        }
        var deleteRow = deleteBtn.closest("tr[data-shipment-id]");
        if (!deleteRow) {
            return;
        }
        if (!window.confirm("Delete this shipment?")) {
            return;
        }
        clearAlert();
        deleteBtn.disabled = true;
        postJson(deleteRow.getAttribute("data-delete-url"), {}).then(function (result) {
            if (!result.ok || !result.data.success) {
                showAlert((result.data && result.data.error) || "Could not delete the shipment.");
                deleteBtn.disabled = false;
                return;
            }
            finishSuccess();
        }).catch(function () {
            showAlert("Could not delete the shipment.");
            deleteBtn.disabled = false;
        });
    });

    var closeBtn = document.getElementById("popup-close");
    if (closeBtn) {
        closeBtn.addEventListener("click", function () {
            window.close();
        });
    }

    var openMode = root.getAttribute("data-open-mode") || "";
    var openShipmentId = root.getAttribute("data-open-shipment-id") || "";
    if (openMode === "add") {
        openAdd();
    } else if (openMode === "edit" && openShipmentId) {
        openEdit(document.querySelector('#shipments-table tr[data-shipment-id="' + openShipmentId + '"]'));
    }
    stripOpenParams();

    var podBox = document.getElementById("pod-complete");
    if (!podBox) {
        return;
    }
    podBox.addEventListener("change", function () {
        var want = podBox.checked;
        if (want) {
            var shipped = podBox.getAttribute("data-ship-qty");
            var ordered = podBox.getAttribute("data-order-qty");
            if (shipped && ordered && Number(shipped) < Number(ordered)) {
                var ok = window.confirm(
                    "Only " + shipped + " of " + ordered + " shipped. Mark POD complete anyway?"
                );
                if (!ok) {
                    podBox.checked = false;
                    return;
                }
            }
        }
        clearAlert();
        document.querySelectorAll("#shipments-table tr[data-shipment-id]").forEach(function (row) {
            row.classList.remove("table-danger");
        });
        podBox.disabled = true;
        postJson(podBox.getAttribute("data-url"), { value: want }).then(function (result) {
            if (result.status === 400 || !result.ok || !result.data.success) {
                showAlert((result.data && result.data.error) || "Could not update POD complete.");
                podBox.checked = false;
                podBox.disabled = false;
                var missing = (result.data && result.data.missing_shipment_ids) || [];
                missing.forEach(function (id) {
                    var row = document.querySelector('#shipments-table tr[data-shipment-id="' + id + '"]');
                    if (row) {
                        row.classList.add("table-danger");
                    }
                });
                return;
            }
            finishSuccess();
        }).catch(function () {
            showAlert("Could not update POD complete.");
            podBox.checked = false;
            podBox.disabled = false;
        });
    });
})();
