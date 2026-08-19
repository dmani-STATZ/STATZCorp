// Netcode: talks to the Django run-start / run-submit endpoints. Computes the
// integrity checksum (HMAC-SHA256 keyed by the session token) to match
// services_marauder.compute_run_checksum. Field order MUST match CHECKSUM_FIELDS.

const CFG = window.MARAUDER;

function getCookie(name) {
    const m = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return m ? decodeURIComponent(m.pop()) : "";
}

async function hmacHex(keyStr, msgStr) {
    if (!(window.crypto && window.crypto.subtle)) return ""; // insecure context fallback
    const enc = new TextEncoder();
    const key = await crypto.subtle.importKey(
        "raw", enc.encode(keyStr), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
    );
    const sig = await crypto.subtle.sign("HMAC", key, enc.encode(msgStr));
    return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function startRun() {
    const res = await fetch(CFG.startUrl, {
        method: "POST",
        headers: { "X-CSRFToken": getCookie("csrftoken"), "Content-Type": "application/json" },
        body: "{}",
    });
    if (!res.ok) throw new Error("start failed: " + res.status);
    return res.json();
}

export async function submitRun(session, stats) {
    // Order must equal server CHECKSUM_FIELDS: seed, score, distance_m,
    // duration_ms, enemies_killed, wave_reached.
    const msg = [
        session.seed,
        stats.score,
        stats.distance_m,
        stats.duration_ms,
        stats.enemies_killed,
        stats.wave_reached,
    ].join("|");
    const checksum = await hmacHex(session.session_token, msg);

    const payload = Object.assign(
        {
            session_token: session.session_token,
            seed: session.seed,
            started_at: session.started_at,
            checksum,
        },
        stats
    );

    const res = await fetch(CFG.submitUrl, {
        method: "POST",
        headers: { "X-CSRFToken": getCookie("csrftoken"), "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        let reason = res.status;
        try { reason = (await res.json()).error || reason; } catch (e) { /* ignore */ }
        throw new Error("submit failed: " + reason);
    }
    return res.json();
}
