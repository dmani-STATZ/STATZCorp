// Backyard Marauder — entry point. Wires the subsystems together, owns the
// shared `game` state, and runs the fixed-timestep update/render.

import {
    VW, VH, PX_PER_METER, SCROLL_BASE, SCROLL_GROWTH, SCROLL_MAX,
    PLAYER_INVULN_MS, PLAYER_STIFFNESS, PLAYER_DAMPING,
    SCORE_PER_METER, BOUNTY_SCORE_MULT, BOUNTY_CREDIT_MULT,
} from "./const.js";
import { makeRng } from "./rng.js";
import { setupCanvas } from "./canvas.js";
import { setupInput } from "./input.js";
import { createAudio } from "./audio.js";
import { createPools, createPlayer } from "./entities.js";
import { createParallax, updateParallax, drawParallax } from "./parallax.js";
import { createDirector, updateDirector } from "./director.js";
import { fireWeapon, updatePlayerBullets } from "./weapons.js";
import { updateEnemies, updateEnemyBullets } from "./enemies.js";
import { updatePowerups, maybeDrop } from "./powerups.js";
import { hitsPlayer, aabb } from "./collision.js";
import { getSprite, CRATE_TINT } from "./sprites.js";
import { drawHud } from "./hud.js";
import { createLoop } from "./loop.js";
import { startRun, submitRun } from "./net.js";
import * as ui from "./gameover.js";

const CFG = window.MARAUDER;
const view = setupCanvas();
const ctx = view.ctx;
const input = setupInput(view);
const audio = createAudio();

let game = null;

function newGame(session) {
    const rng = makeRng(session.seed);
    const g = {
        view, ctx, input, audio, rng, session,
        pools: createPools(),
        player: createPlayer(),
        parallax: createParallax(rng),
        director: createDirector(),
        state: "playing",
        score: 0,
        credits: 0,        // credits earned THIS run (banked on submit)
        distanceM: 0,
        lastDistanceM: 0,
        scrollPx: 0,
        elapsed: 0,
        kills: 0,
        wave: 0,
        maxTier: 1,
        weapon: { type: "vulcan", tier: 1 },
        fireCd: 0,
        // false = fire only while input.firing is true (mouse held / touch
        // active), matching the documented control ("hold left mouse" in
        // marauder.html). autoFire itself is left in place as the toggle
        // weapons.js already gates on, since a future accessibility or
        // touch-friendliness setting may legitimately want to flip this --
        // the bug was the hardcoded `true` default, not the field's existence.
        autoFire: false,
        bountyMs: 0,
        boss: null,
        banner: "",
        bannerMs: 0,
        killedBy: "hull failure",
        creditMult() { return this.bountyMs > 0 ? BOUNTY_CREDIT_MULT : 1; },
        scoreMult() { return this.bountyMs > 0 ? BOUNTY_SCORE_MULT : 1; },
    };
    return g;
}

// ---- damage / death -------------------------------------------------------

function spawnExplosion(g, x, y, color, n) {
    for (let i = 0; i < n; i++) {
        const pt = g.pools.particles.acquire();
        if (!pt) break;
        const a = g.rng.range(0, Math.PI * 2);
        const s = g.rng.range(20, 120);
        pt.x = x; pt.y = y; pt.px = x; pt.py = y;
        pt.vx = Math.cos(a) * s; pt.vy = Math.sin(a) * s;
        pt.life = pt.maxLife = g.rng.range(0.2, 0.5);
        pt.color = color; pt.size = g.rng.int(1, 2);
    }
}

function killEnemy(g, i) {
    const e = g.pools.enemies.active[i];
    const mult = g.scoreMult();
    g.score += e.points * mult;
    g.credits += e.credits * g.creditMult();
    g.kills++;
    spawnExplosion(g, e.x, e.y, e.type === "enforcer" ? "#37d6ff" : "#ffb03b", e.type === "hauler" || e.type === "enforcer" ? 22 : 8);
    maybeDrop(g, e);
    if (g.boss === e) { g.boss = null; g.banner = "ENFORCER DOWN"; g.bannerMs = 2; }
    audio.sfx("explosion");
    g.pools.enemies.releaseAt(i);
}

function damagePlayer(g, source) {
    const p = g.player;
    if (p.invulnMs > 0 || g.state !== "playing") return;
    if (p.shield) {
        p.shield = false;
        p.invulnMs = PLAYER_INVULN_MS;
        audio.sfx("hit");
        return;
    }
    p.hull--;
    p.invulnMs = PLAYER_INVULN_MS;
    p.roll = 0.4;
    g.killedBy = source;
    audio.sfx("hit");
    spawnExplosion(g, p.x, p.y, "#ff5b5b", 6);
    if (p.hull <= 0) endRun(g);
}

function triggerEmp(g) {
    const p = g.player;
    if (p.emp <= 0 || g.state !== "playing") return;
    p.emp--;
    p.roll = 0.5;
    g.pools.eBullets.clear();
    const en = g.pools.enemies;
    for (let i = en.count - 1; i >= 0; i--) {
        const e = en.active[i];
        if (e.type === "enforcer" || e.type === "hauler") {
            e.hp -= 8;
            if (e.hp <= 0) killEnemy(g, i);
        } else {
            killEnemy(g, i);
        }
    }
    spawnExplosion(g, p.x, p.y, "#37d6ff", 24);
    audio.sfx("emp");
}

const ENEMY_LABEL = {
    scout: "a Repo Scout", skiff: "a Syndicate Skiff",
    hauler: "a Guild Hauler", enforcer: "a Corporate Enforcer",
};

// ---- systems --------------------------------------------------------------

function updatePlayerMovement(g, dt) {
    const p = g.player;
    p.px = p.x; p.py = p.y;
    const stiffness = PLAYER_STIFFNESS;
    const damping = PLAYER_DAMPING;
    p.vx += (input.targetX - p.x) * stiffness * dt;
    p.vy += (input.targetY - p.y) * stiffness * dt;
    p.vx -= p.vx * damping * dt;
    p.vy -= p.vy * damping * dt;
    p.x += p.vx * dt;
    p.y += p.vy * dt;
    p.x = Math.max(6, Math.min(VW - 6, p.x));
    p.y = Math.max(10, Math.min(VH - 8, p.y));
    if (p.invulnMs > 0) p.invulnMs -= dt * 1000;
    if (p.roll > 0) p.roll -= dt;
}

function updateParticles(g, dt) {
    const pool = g.pools.particles;
    for (let i = pool.count - 1; i >= 0; i--) {
        const pt = pool.active[i];
        pt.px = pt.x; pt.py = pt.y;
        pt.x += pt.vx * dt;
        pt.y += pt.vy * dt;
        pt.life -= dt;
        if (pt.life <= 0) pool.releaseAt(i);
    }
}

function resolveCollisions(g) {
    const pB = g.pools.pBullets;
    const enemies = g.pools.enemies;

    // Player bullets vs enemies.
    for (let i = pB.count - 1; i >= 0; i--) {
        const b = pB.active[i];
        let consumed = false;
        for (let j = enemies.count - 1; j >= 0; j--) {
            if (j >= enemies.count) continue;
            // Defensive only: given killEnemy's swap-from-top removal and this
            // loop's downward iteration, an already-visited index can never be
            // revisited here in the current code (verified by simulation). This
            // guard exists in case that invariant is ever broken by a future
            // change (e.g. one bullet or explosion killing more than one enemy
            // per iteration) -- it is intentionally left in rather than removed.
            const e = enemies.active[j];
            if (!e._alive || !aabb(b, e)) continue;
            e.hp -= b.dmg;
            spawnExplosion(g, b.x, b.y, b.color, 2);
            if (e.hp <= 0) {
                killEnemy(g, j);
            }
            if (b.pierce > 0) { b.pierce--; }
            else { consumed = true; break; }
        }
        if (consumed) pB.releaseAt(i);
    }

    // Enemy bullets vs player.
    const eB = g.pools.eBullets;
    for (let i = eB.count - 1; i >= 0; i--) {
        const b = eB.active[i];
        if (hitsPlayer(g.player, b)) {
            eB.releaseAt(i);
            damagePlayer(g, "enemy fire");
        }
    }

    // Enemy bodies vs player (ramming).
    for (let j = enemies.count - 1; j >= 0; j--) {
        if (j >= enemies.count) continue;
        // Defensive only: given killEnemy's swap-from-top removal and this
        // loop's downward iteration, an already-visited index can never be
        // revisited here in the current code (verified by simulation). This
        // guard exists in case that invariant is ever broken by a future
        // change (e.g. one bullet or explosion killing more than one enemy
        // per iteration) -- it is intentionally left in rather than removed.
        const e = enemies.active[j];
        if (hitsPlayer(g.player, e)) {
            const label = ENEMY_LABEL[e.type] || "an enemy";
            if (e.type !== "enforcer") killEnemy(g, j);
            damagePlayer(g, `ramming ${label}`);
        }
    }
}

function update(dt) {
    if (!game) return;
    const g = game;

    // EMP is edge-triggered; always clear the queue.
    if (input.empQueued) { triggerEmp(g); input.empQueued = false; }

    if (g.state !== "playing") {
        updateParallax(g.parallax, 12 * dt); // gentle ambient drift
        return;
    }

    g.elapsed += dt;
    const scrollSpeed = Math.min(SCROLL_MAX, SCROLL_BASE + g.elapsed * SCROLL_GROWTH);
    const scrollPxThisFrame = scrollSpeed * dt;
    g.scrollPx += scrollPxThisFrame;
    g.distanceM = Math.floor(g.scrollPx / PX_PER_METER);

    // Distance score.
    if (g.distanceM > g.lastDistanceM) {
        g.score += (g.distanceM - g.lastDistanceM) * SCORE_PER_METER * g.scoreMult();
        g.lastDistanceM = g.distanceM;
    }
    if (g.bountyMs > 0) g.bountyMs = Math.max(0, g.bountyMs - dt * 1000);
    if (g.bannerMs > 0) g.bannerMs -= dt;

    updateParallax(g.parallax, scrollPxThisFrame);
    updatePlayerMovement(g, dt);
    fireWeapon(g, dt);
    updatePlayerBullets(g, dt);
    updateDirector(g, dt);
    updateEnemies(g, dt);
    updateEnemyBullets(g, dt);
    updatePowerups(g, dt);
    updateParticles(g, dt);
    resolveCollisions(g);
}

// ---- rendering ------------------------------------------------------------

function ipos(o, a) { return { x: o.px + (o.x - o.px) * a, y: o.py + (o.y - o.py) * a }; }

function drawSprite(key, cx, cy, alphaScale) {
    const s = getSprite(key);
    if (!s) return;
    const w = s.width * (alphaScale || 1);
    const h = s.height;
    ctx.drawImage(s, Math.round(cx - w / 2), Math.round(cy - h / 2), w, h);
}

function render(alpha) {
    if (!game) return;
    const g = game;
    drawParallax(ctx, g.parallax);

    // Powerup crates.
    for (let i = 0; i < g.pools.powerups.count; i++) {
        const c = g.pools.powerups.active[i];
        const pos = ipos(c, alpha);
        drawSprite("crate", pos.x, pos.y, 1);
        ctx.fillStyle = CRATE_TINT[c.kind] || "#ffd83b";
        ctx.fillRect(Math.round(pos.x) - 2, Math.round(pos.y) - 2, 4, 4);
    }

    // Enemies.
    for (let i = 0; i < g.pools.enemies.count; i++) {
        const e = g.pools.enemies.active[i];
        const pos = ipos(e, alpha);
        drawSprite(e.type, pos.x, pos.y, 1);
    }

    // Player bullets.
    for (let i = 0; i < g.pools.pBullets.count; i++) {
        const b = g.pools.pBullets.active[i];
        const pos = ipos(b, alpha);
        ctx.fillStyle = b.color;
        ctx.fillRect(Math.round(pos.x - b.w / 2), Math.round(pos.y - b.h / 2), b.w, b.h);
    }
    // Enemy bullets.
    for (let i = 0; i < g.pools.eBullets.count; i++) {
        const b = g.pools.eBullets.active[i];
        const pos = ipos(b, alpha);
        ctx.fillStyle = b.color;
        ctx.fillRect(Math.round(pos.x - b.w / 2), Math.round(pos.y - b.h / 2), b.w, b.h);
    }

    // Player ship (blink during i-frames, squash for barrel roll).
    const p = g.player;
    const ppos = ipos(p, alpha);
    const blink = p.invulnMs > 0 && Math.floor(g.elapsed * 20) % 2 === 0;
    if (g.state === "playing" && !blink) {
        const rollScale = p.roll > 0 ? Math.abs(Math.cos(p.roll * 8)) * 0.9 + 0.1 : 1;
        if (p.shield) {
            ctx.strokeStyle = "#37d6ff";
            ctx.beginPath();
            ctx.arc(Math.round(ppos.x), Math.round(ppos.y), 9, 0, Math.PI * 2);
            ctx.stroke();
        }
        drawSprite("player", ppos.x, ppos.y, rollScale);
    }

    // Particles.
    for (let i = 0; i < g.pools.particles.count; i++) {
        const pt = g.pools.particles.active[i];
        const pos = ipos(pt, alpha);
        ctx.globalAlpha = Math.max(0, pt.life / pt.maxLife);
        ctx.fillStyle = pt.color;
        ctx.fillRect(Math.round(pos.x), Math.round(pos.y), pt.size, pt.size);
    }
    ctx.globalAlpha = 1;

    if (g.state === "playing") drawHud(ctx, g);
}

const loop = createLoop(update, render);

// ---- run lifecycle --------------------------------------------------------

async function endRun(g) {
    g.state = "dead";
    audio.sfx("gameover");
    const stats = {
        score: Math.round(g.score),
        distance_m: g.distanceM,
        duration_ms: Math.round(g.elapsed * 1000),
        credits_earned: Math.round(g.credits),
        enemies_killed: g.kills,
        wave_reached: g.wave,
        max_weapon_tier: g.maxTier,
    };
    const summary = Object.assign({ killed_by: g.killedBy }, stats);
    try {
        const result = await submitRun(g.session, stats);
        // Refresh cached boards + credits badge for subsequent screens.
        if (result.global_top) CFG.globalTop = result.global_top;
        if (result.personal_top) CFG.personalTop = result.personal_top;
        if (typeof result.credits_total === "number") {
            const badge = document.getElementById("mar-credits-badge");
            if (badge) badge.textContent = result.credits_total + " cr";
        }
        ui.showGameOver(summary, result);
    } catch (err) {
        ui.showGameOver(summary, "error");
    }
}

async function launch() {
    ui.setStartMessage("Spooling hyper-drive…");
    audio.startMusic();
    try {
        const session = await startRun();
        game = newGame(session);
        ui.hideOverlays();
        if (!loop.running) loop.start();
    } catch (err) {
        ui.setStartMessage("Launch failed — check your connection and retry.");
    }
}

function toStartScreen() {
    ui.populateStartScreen(CFG);
    ui.showStart();
    if (!loop.running) loop.start(); // animate the backdrop behind the menu
}

// ---- wire DOM -------------------------------------------------------------

document.getElementById("mar-launch-btn").addEventListener("click", launch);
document.getElementById("mar-again-btn").addEventListener("click", launch);
document.getElementById("mar-mute").addEventListener("click", (e) => {
    audio.resume();
    const muted = audio.toggleMute();
    e.target.textContent = muted ? "SND: OFF" : "SND: ON";
});

toStartScreen();
