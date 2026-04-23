/**
 * STATZ Corporation - Theme toggle (Bootstrap 5.3)
 * Sets data-bs-theme on <html>, persists to localStorage, syncs user preference via AJAX.
 */

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
        const cookies = document.cookie.split(";");
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + "=")) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

function setThemeOnDocument(theme) {
    const t = theme === "dark" || theme === "light" ? theme : "light";
    document.documentElement.setAttribute("data-bs-theme", t);
    try {
        localStorage.setItem("theme", t);
    } catch (e) {
        /* ignore */
    }
    return t;
}

function getThemeFromDocument() {
    return document.documentElement.getAttribute("data-bs-theme") === "dark" ? "dark" : "light";
}

function updateThemeIcon(theme) {
    const icon = document.getElementById("theme-toggle-icon");
    if (!icon) return;
    while (icon.firstChild) {
        icon.removeChild(icon.firstChild);
    }
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
    path.setAttribute("stroke-width", "2");
    if (theme === "dark") {
        path.setAttribute("d", "M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z");
    } else {
        path.setAttribute(
            "d",
            "M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"
        );
    }
    icon.appendChild(path);
}

(function applyStoredTheme() {
    let stored = "light";
    try {
        stored = localStorage.getItem("theme") || "light";
    } catch (e) {
        /* ignore */
    }
    if (stored !== "dark" && stored !== "light") {
        stored = "light";
    }
    document.documentElement.setAttribute("data-bs-theme", stored);
})();

document.addEventListener("DOMContentLoaded", function () {
    const btn = document.getElementById("theme-toggle");
    updateThemeIcon(getThemeFromDocument());
    if (!btn) return;

    btn.addEventListener("click", function () {
        const current = document.documentElement.getAttribute("data-bs-theme");
        const newTheme = current === "dark" ? "light" : "dark";
        setThemeOnDocument(newTheme);
        updateThemeIcon(newTheme);
        window.dispatchEvent(new Event("themeChanged"));
        if (typeof window.CURRENT_USER_ID === "undefined") {
            return;
        }
        fetch("/users/settings/ajax/save/", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCookie("csrftoken"),
            },
            body: JSON.stringify({
                user_id: window.CURRENT_USER_ID,
                setting_name: "theme",
                setting_value: newTheme,
                setting_type: "string",
            }),
        }).catch(function () {
            /* ignore */
        });
    });
});
