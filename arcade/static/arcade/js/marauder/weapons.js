// Weapon archetypes. Upgrading a weapon widens/alters its coverage pattern
// rather than only boosting raw damage. Tier ranges 1..5.

import { VH } from "./const.js";

function spawn(game, x, y, vx, vy, opts) {
    const b = game.pools.pBullets.acquire();
    if (!b) return;
    b.x = x; b.y = y; b.px = x; b.py = y;
    b.vx = vx; b.vy = vy;
    b.faction = 0;
    b.dmg = opts.dmg;
    b.w = opts.w; b.h = opts.h;
    b.kind = opts.kind;
    b.color = opts.color;
    b.homing = !!opts.homing;
    b.target = null;
    b.pierce = opts.pierce || 0;
    b.life = opts.life || 3;
}

export const WEAPONS = {
    vulcan: {
        name: "Standard Vulcan",
        cadence: 0.11,
        fire(game, p, tier) {
            const dmg = 1 + Math.floor(tier / 2);
            const spd = -300;
            const lane = 3 + tier * 0.2;
            spawn(game, p.x - lane, p.y - 6, 0, spd, { dmg, w: 2, h: 6, kind: "bolt", color: "#ffe23b" });
            spawn(game, p.x + lane, p.y - 6, 0, spd, { dmg, w: 2, h: 6, kind: "bolt", color: "#ffe23b" });
            if (tier >= 3) spawn(game, p.x, p.y - 8, 0, spd, { dmg, w: 2, h: 6, kind: "bolt", color: "#fff08a" });
            if (tier >= 5) {
                spawn(game, p.x - lane, p.y - 6, -30, spd, { dmg, w: 2, h: 6, kind: "bolt", color: "#ffe23b" });
                spawn(game, p.x + lane, p.y - 6, 30, spd, { dmg, w: 2, h: 6, kind: "bolt", color: "#ffe23b" });
            }
        },
    },
    scatter: {
        name: "Bounty Scatter",
        cadence: 0.16,
        fire(game, p, tier) {
            const dmg = 1;
            const spd = 280;
            const shots = 1 + tier; // tier1 -> 2-way(±), grows to ~6-way fan
            const spread = 0.5;      // radians total half-width-ish
            const cols = ["#ff5bd0", "#ffd83b", "#37d6ff"];
            for (let i = 0; i < shots; i++) {
                const t = shots === 1 ? 0 : (i / (shots - 1)) * 2 - 1; // -1..1
                const ang = -Math.PI / 2 + t * spread;
                spawn(game, p.x, p.y - 6, Math.cos(ang) * spd, Math.sin(ang) * spd,
                    { dmg, w: 2, h: 2, kind: "pellet", color: cols[i % cols.length] });
            }
        },
    },
    laser: {
        name: "Corporate Laser",
        cadence: 0.28,
        fire(game, p, tier) {
            const dmg = 1 + Math.floor(tier / 2);
            const w = 3 + tier;      // wider beam per tier
            spawn(game, p.x, p.y - 20, 0, -520,
                { dmg, w, h: 26, kind: "beam", color: "#4dffff", pierce: 99, life: VH / 520 + 0.2 });
        },
    },
    seeker: {
        name: "Seeker Micro-Missiles",
        cadence: 0.22,
        fire(game, p, tier) {
            const dmg = 1;
            // 2 forward bolts...
            spawn(game, p.x - 4, p.y - 6, 0, -300, { dmg, w: 2, h: 6, kind: "bolt", color: "#ff8a3b" });
            spawn(game, p.x + 4, p.y - 6, 0, -300, { dmg, w: 2, h: 6, kind: "bolt", color: "#ff8a3b" });
            // ...plus homing arcs (count scales with tier).
            const arcs = 1 + Math.floor(tier / 2);
            for (let i = 0; i < arcs; i++) {
                const dir = i % 2 === 0 ? -1 : 1;
                spawn(game, p.x + dir * 6, p.y, dir * 90, -160,
                    { dmg: dmg + 1, w: 3, h: 3, kind: "missile", color: "#ff3b3b", homing: true, life: 3 });
            }
        },
    },
};

export const WEAPON_ORDER = ["vulcan", "scatter", "laser", "seeker"];

export function fireWeapon(game, dt) {
    game.fireCd -= dt;
    if (!game.input.firing && !game.autoFire) return;
    const def = WEAPONS[game.weapon.type];
    if (game.fireCd > 0) return;
    game.fireCd = def.cadence;
    def.fire(game, game.player, game.weapon.tier);
    if (game.audio) game.audio.sfx("shoot");
}

// Move player bullets, apply homing steering, cull spent ones.
export function updatePlayerBullets(game, dt) {
    const pool = game.pools.pBullets;
    const enemies = game.pools.enemies;
    for (let i = pool.count - 1; i >= 0; i--) {
        const b = pool.active[i];
        b.px = b.x; b.py = b.y;
        if (b.homing) {
            // Retarget to nearest live enemy if needed.
            if (!b.target || !b.target._alive) {
                let best = null, bd = 1e9;
                for (let j = 0; j < enemies.count; j++) {
                    const e = enemies.active[j];
                    const d = (e.x - b.x) ** 2 + (e.y - b.y) ** 2;
                    if (d < bd) { bd = d; best = e; }
                }
                b.target = best;
            }
            if (b.target) {
                const ang = Math.atan2(b.target.y - b.y, b.target.x - b.x);
                const spd = Math.hypot(b.vx, b.vy) || 260;
                const desiredX = Math.cos(ang) * spd;
                const desiredY = Math.sin(ang) * spd;
                b.vx += (desiredX - b.vx) * Math.min(1, dt * 6);
                b.vy += (desiredY - b.vy) * Math.min(1, dt * 6);
            }
        }
        b.x += b.vx * dt;
        b.y += b.vy * dt;
        b.life -= dt;
        if (b.y < -10 || b.y > VH + 10 || b.x < -10 || b.x > 330 || b.life <= 0) {
            pool.releaseAt(i);
        }
    }
}
