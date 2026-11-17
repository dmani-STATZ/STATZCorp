/* Opens the CLIN shipments popup and reloads this page once, after it closes. */
(function () {
    if (window.__clinShipmentsPopupBound) {
        return;
    }
    window.__clinShipmentsPopupBound = true;

    var watcher = null;

    function watchPopup(popup) {
        if (watcher !== null) {
            window.clearInterval(watcher);
            watcher = null;
        }
        watcher = window.setInterval(function () {
            if (!popup || !popup.closed) {
                return;
            }
            window.clearInterval(watcher);
            watcher = null;
            if (window.__clinShipmentsDirty) {
                window.__clinShipmentsDirty = false;
                window.location.reload();
            }
        }, 500);
    }

    window.openClinShipmentsPopup = function (buttonEl) {
        if (!buttonEl) {
            return null;
        }
        var url = buttonEl.getAttribute("data-popup-url");
        if (!url) {
            return null;
        }
        var popup = window.open(
            url,
            "clinShipmentsPopup",
            "width=1100,height=760,resizable=yes,scrollbars=yes"
        );
        if (!popup) {
            if (typeof window.notify === "function") {
                window.notify("warning", "Popup blocked. Allow popups for this site.");
            }
            return null;
        }
        watchPopup(popup);
        return popup;
    };

    document.addEventListener("click", function (event) {
        var button = event.target.closest(".js-open-clin-shipments-popup");
        if (!button) {
            return;
        }
        event.preventDefault();
        window.openClinShipmentsPopup(button);
    });
})();
