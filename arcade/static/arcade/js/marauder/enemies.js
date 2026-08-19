// Enemy archetypes + AI. Enemies are spawned by the wave director/formations
// and updated here each fixed step. Enemy bullets live in the eBullets pool.

import { VW, VH } from "./const.js";

export const ENEMY_DEFS = {
    // Repo Scout — fast zig-zag dives, straight kinetic bursts. Swarm fodder.
    scout: {
        w: 10, h: 8, radius: 5, hp: 2, points: 10, credits: 3, loot: "low",
        fireEvery: 3.2, speed: 70, sprite: "scout",
    },
    // Syndicate Skiff — drifts along the top third, matches player X, aimed bursts.
    skiff: {
        w: 12, h: 8, radius: 6, hp: 3, points: 25, credits: 6, loot: "low",
        fireEvery: 4.0, speed: 40, sprite: "skiff",
    },
    // Guild Hauler — slow heavy barricade down the center, big loot on death.
    hauler: {
        w: 24, h: 20, radius: 12, hp: 34, points: 150, credits: 40, loot: "high",
        fireEvery: 2.4, speed: 22, sprite: "hauler",
    },
    // Corporate Enforcer — mini-boss with dual rotating hardpoints / laser gates.
    enforcer: {
        w: 40, h: 24, radius: 18, hp: 130, points: 1500, credits: 220, loot: "boss",
        fireEvery: 0.09, speed: 18, sprite: "enforcer",
    },
};

export function spawnEnemy(game, type, x, y) {
    const def = ENEMY_DEFS[type];
    if (!def) return null;
    const e = game.pools.enemies.acquire();
    if (!e) return null;
    e.type = type;
    e.x = x; e.y = y; e.px = x; e.py = y;
    e.baseX = x;
    e.vx = 0; e.vy = def.speed;
    e.w = def.w; e.h = def.h; e.radius = def.radius;
    e.hp = def.hp; e.maxHp = def.hp;
    e.points = def.points; e.credits = def.credits; e.loot = def.loot;
    e.fireEvery = def.fireEvery;
    e.fireTimer = def.fireEvery * (0.4 + game.rng.next() * 0.6);
    e.t = 0; e.phase = 0; e.angle = 0;
    if (type === "enforcer") game.boss = e;
    return e;
}

function eShot(game, x, y, vx, vy, opts) {
    const b = game.pools.eBullets.acquire();
    if (!b) return;
    b.x = x; b.y = y; b.px = x; b.py = y;
    b.vx = vx; b.vy = vy;
    b.faction = 1;
    b.dmg = 1;
    b.w = opts.w || 3; b.h = opts.h || 3;
    b.kind = opts.kind || "kinetic";
    b.color = opts.color || "#ff4d4d";
    b.life = 6; b.homing = false; b.pierce = 0;
}

function aimAt(fromX, fromY, tx, ty, spd) {
    const ang = Math.atan2(ty - fromY, tx - fromX);
    return { vx: Math.cos(ang) * spd, vy: Math.sin(ang) * spd };
}

export function updateEnemies(game, dt) {
    const pool = game.pools.enemies;
    const p = game.player;
    for (let i = pool.count - 1; i >= 0; i--) {
        const e = pool.active[i];
        e.px = e.x; e.py = e.y;
        e.t += dt;
        e.fireTimer -= dt;

        switch (e.type) {
            case "scout": {
                e.y += e.vy * dt;
                e.x = e.baseX + Math.sin(e.t * 4) * 26;
                if (e.fireTimer <= 0) {
                    e.fireTimer = e.fireEvery;
                    eShot(game, e.x, e.y + 5, 0, 150, { color: "#ff7a7a" });
                }
                break;
            }
            case "skiff": {
                // Descend into the top third, then hold and track player X.
                const holdY = 51 + (e.baseX % 3) * 12;
                if (e.y < holdY) e.y += e.vy * dt;
                e.x += (p.x - e.x) * Math.min(1, dt * 0.6);
                if (e.fireTimer <= 0) {
                    e.fireTimer = e.fireEvery;
                    const s1 = aimAt(e.x - 3, e.y, p.x, p.y, 130);
                    const s2 = aimAt(e.x + 3, e.y, p.x, p.y, 130);
                    eShot(game, e.x - 3, e.y + 4, s1.vx, s1.vy, { color: "#c98bff" });
                    eShot(game, e.x + 3, e.y + 4, s2.vx, s2.vy, { color: "#c98bff" });
                }
                break;
            }
            case "hauler": {
                e.y += e.vy * dt;
                if (e.fireTimer <= 0) {
                    e.fireTimer = e.fireEvery;
                    for (let a = -1; a <= 1; a++) {
                        eShot(game, e.x, e.y + 10, a * 40, 90, { w: 3, h: 3, color: "#e8c85a" });
                    }
                }
                break;
            }
            case "enforcer": {
                // Enter, then hover and sweep dual rotating hardpoints.
                if (e.y < 69) e.y += e.vy * dt;
                else e.x = VW / 2 + Math.sin(e.t * 0.6) * 70;
                e.angle += dt * 1.4;
                if (e.y >= 69 && e.fireTimer <= 0) {
                    e.fireTimer = e.fireEvery;
                    // Two hardpoints firing along a rotating (sweeping) direction.
                    for (const hp of [-16, 16]) {
                        const ang = Math.PI / 2 + Math.sin(e.angle + (hp > 0 ? Math.PI : 0)) * 0.9;
                        eShot(game, e.x + hp, e.y + 8, Math.cos(ang) * 160, Math.sin(ang) * 160,
                            { w: 3, h: 5, kind: "gate", color: "#37d6ff" });
                    }
                }
                break;
            }
        }

        // Cull enemies that leave the bottom (bosses never do while alive).
        if (e.y > VH + 24) {
            if (game.boss === e) game.boss = null;
            pool.releaseAt(i);
        }
    }
}

export function updateEnemyBullets(game, dt) {
    const pool = game.pools.eBullets;
    for (let i = pool.count - 1; i >= 0; i--) {
        const b = pool.active[i];
        b.px = b.x; b.py = b.y;
        b.x += b.vx * dt;
        b.y += b.vy * dt;
        b.life -= dt;
        if (b.y < -12 || b.y > VH + 12 || b.x < -12 || b.x > VW + 12 || b.life <= 0) {
            pool.releaseAt(i);
        }
    }
}
