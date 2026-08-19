// Start / game-over overlay DOM helpers: renders the leaderboard tables and the
// run summary. Game state transitions are driven by main.js.

const $ = (id) => document.getElementById(id);

// r.username on the global board is server-derived from get_full_name() or
// username -- Django's default User model puts no character restriction on
// first_name/last_name, so it must be escaped before it reaches innerHTML.
// r.date (used on the personal board) is server-formatted and never
// user-controlled, but it's escaped too rather than special-cased, so this
// stays correct if that ever changes.
function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
}

function fillTable(tbodyId, rows, personal) {
    const tb = $(tbodyId);
    if (!tb) return;
    tb.innerHTML = "";
    if (!rows || !rows.length) {
        tb.innerHTML = `<tr><td colspan="3" style="color:#5f74a8">—</td></tr>`;
        return;
    }
    for (const r of rows) {
        const label = escapeHtml(personal ? r.date : (r.username || "—"));
        tb.insertAdjacentHTML(
            "beforeend",
            `<tr><td>${r.rank}</td><td>${label}</td><td>${r.score}</td></tr>`
        );
    }
}

export function populateStartScreen(cfg) {
    fillTable("mar-start-global", cfg.globalTop, false);
    fillTable("mar-start-personal", cfg.personalTop, true);
}

export function showStart() {
    $("mar-start-overlay").classList.remove("mar-hidden");
    $("mar-over-overlay").classList.add("mar-hidden");
}

export function hideOverlays() {
    $("mar-start-overlay").classList.add("mar-hidden");
    $("mar-over-overlay").classList.add("mar-hidden");
}

export function setStartMessage(msg) {
    $("mar-start-msg").textContent = msg || "";
}

export function showGameOver(summary, result) {
    const over = $("mar-over-overlay");
    $("mar-over-title").textContent = "Hull Breached";
    $("mar-over-killed").textContent = `Taken out by: ${summary.killed_by}`;

    let rankLine = "";
    if (result && result.run_status === "valid") {
        rankLine = `Global rank #${result.global_rank} · Your rank #${result.personal_rank}`;
    } else if (result && result.run_status) {
        rankLine = `Run ${result.run_status} — not counted on the board.`;
    } else if (result === "error") {
        rankLine = "Score submission failed (saved locally only).";
    }

    $("mar-over-stats").innerHTML = `
        <div class="col-6">Score: <span class="mar-key">${summary.score}</span></div>
        <div class="col-6">Distance: <span class="mar-key">${summary.distance_m}m</span></div>
        <div class="col-6">Kills: <span class="mar-key">${summary.enemies_killed}</span></div>
        <div class="col-6">Wave: <span class="mar-key">${summary.wave_reached}</span></div>
        <div class="col-6">Credits: <span class="mar-key">${summary.credits_earned}</span></div>
        <div class="col-6">Max Tier: <span class="mar-key">${summary.max_weapon_tier}</span></div>
        <div class="col-12 mt-1" style="color:#37d6ff">${rankLine}</div>
    `;

    const g = result && result.global_top ? result.global_top : window.MARAUDER.globalTop;
    const p = result && result.personal_top ? result.personal_top : window.MARAUDER.personalTop;
    fillTable("mar-over-global", g, false);
    fillTable("mar-over-personal", p, true);

    over.classList.remove("mar-hidden");
}
