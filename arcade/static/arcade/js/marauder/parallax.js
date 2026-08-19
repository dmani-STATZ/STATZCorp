// Three-layer parallax backdrop: far starfield/nebula, mid corporate billboards
// & orbital junk, foreground asteroid fragments. Deterministic layout via rng.

import { VW, VH } from "./const.js";

function makeLayer(rng, n, spec) {
    const items = [];
    for (let i = 0; i < n; i++) {
        items.push({
            x: rng.range(0, VW),
            y: rng.range(0, VH),
            size: rng.range(spec.min, spec.max),
            hue: spec.hues ? rng.pick(spec.hues) : "#ffffff",
        });
    }
    return items;
}

export function createParallax(rng) {
    return {
        far: makeLayer(rng, 60, { min: 1, max: 1, hues: ["#8fa7d6", "#c9d6ff", "#5f74a8"] }),
        nebula: makeLayer(rng, 5, { min: 40, max: 90, hues: ["#1b2a55", "#3a1b55", "#123044"] }),
        mid: makeLayer(rng, 8, { min: 6, max: 12, hues: ["#ffcf3b", "#37d6ff", "#ff5bd0"] }),
        fore: makeLayer(rng, 10, { min: 3, max: 7, hues: ["#6b5a3a", "#7a6a4a", "#5a4a30"] }),
        factors: { far: 0.15, nebula: 0.08, mid: 0.5, fore: 1.1 },
    };
}

function advance(items, dy) {
    for (const it of items) {
        it.y += dy;
        if (it.y > VH + it.size) { it.y -= VH + it.size * 2; it.x = (it.x * 1.1) % VW; }
    }
}

export function updateParallax(px, scrollPx) {
    advance(px.nebula, scrollPx * px.factors.nebula);
    advance(px.far, scrollPx * px.factors.far);
    advance(px.mid, scrollPx * px.factors.mid);
    advance(px.fore, scrollPx * px.factors.fore);
}

export function drawParallax(ctx, px) {
    ctx.fillStyle = "#05060f";
    ctx.fillRect(0, 0, VW, VH);
    // Nebula clouds
    ctx.globalAlpha = 0.35;
    for (const n of px.nebula) {
        ctx.fillStyle = n.hue;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.size, 0, Math.PI * 2);
        ctx.fill();
    }
    ctx.globalAlpha = 1;
    // Far stars
    for (const s of px.far) {
        ctx.fillStyle = s.hue;
        ctx.fillRect(s.x | 0, s.y | 0, 1, 1);
    }
    // Mid billboards / orbital junk (little glowing boxes)
    for (const m of px.mid) {
        ctx.fillStyle = m.hue;
        ctx.fillRect((m.x | 0) - m.size / 2, (m.y | 0) - m.size / 4, m.size, m.size / 2);
        ctx.fillStyle = "rgba(0,0,0,0.4)";
        ctx.fillRect((m.x | 0) - m.size / 2 + 1, (m.y | 0) - m.size / 4 + 1, m.size - 2, 1);
    }
    // Foreground asteroids
    for (const f of px.fore) {
        ctx.fillStyle = f.hue;
        ctx.beginPath();
        ctx.arc(f.x, f.y, f.size, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "rgba(255,255,255,0.15)";
        ctx.fillRect(f.x - f.size / 2, f.y - f.size / 2, 1, 1);
    }
}
