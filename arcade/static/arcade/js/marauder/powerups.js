// Branded crate drops + effects. Crates float down with a slight spin and are
// scooped on contact. Effects follow the GDD economy.

import {
    VH, BOUNTY_MS, PLAYER_START_EMP,
    LOW_LOOT_CHANCE_BASE, LOW_LOOT_CHANCE_FINAL, LOOT_RAMP_SECONDS,
} from "./const.js";
import { WEAPON_ORDER } from "./weapons.js";
import { hitsPlayer } from "./collision.js";

const KINDS = ["plating", "overclock", "nuke", "bounty"];

// Ramps the low-tier (scout) crate-drop chance from LOW_LOOT_CHANCE_BASE down
// to LOW_LOOT_CHANCE_FINAL (the old flat 8%) over LOOT_RAMP_SECONDS. See the
// const.js comment on this block for why: with wave 1 now only 1-2 enemies,
// an 8% roll meant most players got zero crates in their first couple waves.
function lowLootChance(elapsed) {
    const t = Math.min(1, elapsed / LOOT_RAMP_SECONDS);
    return LOW_LOOT_CHANCE_BASE + (LOW_LOOT_CHANCE_FINAL - LOW_LOOT_CHANCE_BASE) * t;
}

export function spawnPowerup(game, x, y, kind) {
    const c = game.pools.powerups.acquire();
    if (!c) return;
    c.x = x; c.y = y; c.px = x; c.py = y;
    c.vy = 34;
    c.kind = kind;
    c.spin = 0;
    c.w = 10; c.h = 10;
}

// Decide whether a killed enemy drops a crate, based on its loot tier.
export function maybeDrop(game, e) {
    const r = game.rng;
    if (e.loot === "boss") {
        // Boss showers loot.
        spawnPowerup(game, e.x - 14, e.y, "overclock");
        spawnPowerup(game, e.x, e.y, "plating");
        spawnPowerup(game, e.x + 14, e.y, r.chance(0.5) ? "nuke" : "bounty");
        return;
    }
    if (e.loot === "high") {
        spawnPowerup(game, e.x, e.y, r.pick(["overclock", "nuke", "bounty", "plating"]));
        return;
    }
    // low tier -- chance ramps down from LOW_LOOT_CHANCE_BASE to
    // LOW_LOOT_CHANCE_FINAL; see lowLootChance() above.
    if (r.chance(lowLootChance(game.elapsed))) {
        spawnPowerup(game, e.x, e.y, r.pick(KINDS));
    }
}

function applyPowerup(game, kind) {
    const p = game.player;
    switch (kind) {
        case "plating":
            if (p.hull < p.maxHull) p.hull++;
            else p.shield = true;                 // temporary 1-hit energy ring
            break;
        case "overclock":
            if (game.weapon.tier < 5) {
                game.weapon.tier++;
            } else {
                // At max tier: hand over a fresh archetype (kept engaging, never a
                // dead pickup) and a credit bonus, per the GDD's max-tier payout.
                const others = WEAPON_ORDER.filter((w) => w !== game.weapon.type);
                game.weapon.type = game.rng.pick(others);
                game.weapon.tier = 3;
                game.credits += 250 * game.creditMult();
            }
            game.maxTier = Math.max(game.maxTier, game.weapon.tier);
            break;
        case "nuke":
            p.emp = Math.min(p.emp + 1, PLAYER_START_EMP + 4);
            break;
        case "bounty":
            game.bountyMs = BOUNTY_MS;
            break;
    }
    if (game.audio) game.audio.sfx("pickup");
}

export function updatePowerups(game, dt) {
    const pool = game.pools.powerups;
    const p = game.player;
    for (let i = pool.count - 1; i >= 0; i--) {
        const c = pool.active[i];
        c.px = c.x; c.py = c.y;
        c.y += c.vy * dt;
        c.spin += dt * 3;
        if (hitsPlayer(p, c)) {
            applyPowerup(game, c.kind);
            pool.releaseAt(i);
            continue;
        }
        if (c.y > VH + 12) pool.releaseAt(i);
    }
}
