// Procedural wave engine. Every WAVE_INTERVAL seconds it allocates a threat
// budget (THREAT_BASE + elapsed * THREAT_SCALING), then "buys" enemy formations
// from a cost pool. The Corporate Enforcer mini-boss spawns on distance
// milestones, independent of the budget.
//
// THREE THINGS WERE BROKEN HERE. Documented so nobody reintroduces them:
//
//  1. FLAT DIFFICULTY. The spend loop was capped at a hardcoded 12 purchases.
//     Twelve skiffs cost 36 budget, and budget reaches 36 at ~36 seconds, so
//     every budget point earned after that was discarded. The wave size ramp is
//     now WAVE_PURCHASE_BASE + elapsed * WAVE_PURCHASE_GROWTH, capped by
//     WAVE_PURCHASE_CAP -- an actual curve instead of a wall.
//
//  2. DIFFICULTY WENT BACKWARDS AT 45s. Rolling a hauler did `break`, ending
//     the whole wave. Haulers unlock at 45s with a 20% roll per purchase, so
//     from then on waves ended after ~5 purchases instead of running the full
//     12. The game got EASIER exactly when it should have opened up. Haulers
//     are now capped per wave (MAX_HAULERS_PER_WAVE) instead of terminating it.
//
//  3. SKIPPED BOSSES. `nextBossM` advanced even when spawnEnemy returned null
//     (enemy pool full), silently costing you a boss and pushing the next one
//     1500m out. The milestone now only advances on a successful spawn.

import {
    VW,
    WAVE_INTERVAL, WAVE_INTERVAL_MIN, WAVE_INTERVAL_DECAY,
    THREAT_BASE, THREAT_SCALING,
    WAVE_PURCHASE_BASE, WAVE_PURCHASE_GROWTH, WAVE_PURCHASE_CAP,
    MAX_HAULERS_PER_WAVE, MAX_LIVE_ENEMIES,
    GROUP_MIN_BASE, GROUP_MAX_BASE, GROUP_MIN_FINAL, GROUP_MAX_FINAL, GROUP_RAMP_SECONDS,
    SKIFF_UNLOCK_S, HAULER_UNLOCK_S, SKIFF_CHANCE, HAULER_CHANCE,
    PINCER_UNLOCK_S, BOSS_EVERY_M,
} from "./const.js";
import { FORMATIONS, EARLY_FORMATIONS } from "./formations.js";
import { spawnEnemy } from "./enemies.js";

const COST = { scout: 1, skiff: 3, hauler: 8 };

export function createDirector() {
    return {
        timer: WAVE_INTERVAL,
        wave: 0,
        nextBossM: BOSS_EVERY_M,
        bossActive: false,
    };
}

// Waves arrive faster as the run deepens. This is the PRESSURE ramp, and it's
// what keeps the game escalating after world scroll caps out at 120s.
function waveInterval(elapsed) {
    return Math.max(WAVE_INTERVAL_MIN, WAVE_INTERVAL - elapsed * WAVE_INTERVAL_DECAY);
}

// Formations a single wave may spawn. This is the SIZE ramp.
function purchaseLimit(elapsed) {
    return Math.min(
        WAVE_PURCHASE_CAP,
        Math.floor(WAVE_PURCHASE_BASE + elapsed * WAVE_PURCHASE_GROWTH),
    );
}

// Formation size ramps in the same spirit as purchaseLimit above: linear from
// BASE to FINAL over GROUP_RAMP_SECONDS, then clamped at FINAL. This is the
// "how many enemies does one purchase actually deliver" lever -- it used to
// be a flat GROUP_MIN..GROUP_MAX for the whole run.
function groupRange(elapsed) {
    const t = Math.min(1, elapsed / GROUP_RAMP_SECONDS);
    const min = Math.round(GROUP_MIN_BASE + (GROUP_MIN_FINAL - GROUP_MIN_BASE) * t);
    const max = Math.round(GROUP_MAX_BASE + (GROUP_MAX_FINAL - GROUP_MAX_BASE) * t);
    return [min, max];
}

export function updateDirector(game, dt) {
    const d = game.director;

    d.bossActive = !!game.boss;

    // --- Boss cadence by distance -------------------------------------------
    if (!d.bossActive && game.distanceM >= d.nextBossM) {
        const boss = spawnEnemy(game, "enforcer", VW / 2, -30);
        if (boss) {
            d.nextBossM += BOSS_EVERY_M;
            game.wave++;
            if (game.audio) game.audio.sfx("boss");
        }
        // If the pool was full, nextBossM is left alone so we retry next tick
        // rather than losing the boss. Either way, no normal wave this tick.
        return;
    }

    // Hold off new waves while a boss is alive — the Enforcer is a duel.
    if (d.bossActive) return;

    // --- Wave timer ----------------------------------------------------------
    d.timer -= dt;
    if (d.timer > 0) return;
    d.timer = waveInterval(game.elapsed);
    d.wave++;
    game.wave = Math.max(game.wave, d.wave);

    // --- Spend the threat budget --------------------------------------------
    let budget = THREAT_BASE + game.elapsed * THREAT_SCALING;
    const maxPurchases = purchaseLimit(game.elapsed);

    // Unlock tougher enemies as the run deepens.
    const canSkiff = game.elapsed > SKIFF_UNLOCK_S;
    const canHauler = game.elapsed > HAULER_UNLOCK_S;
    const [groupMin, groupMax] = groupRange(game.elapsed);
    // pincer spawns at both screen edges at once -- excluded until
    // PINCER_UNLOCK_S so the opening never hands the player an unreachable,
    // full-width split. See the const.js comment on PINCER_UNLOCK_S.
    const formationPool = game.elapsed > PINCER_UNLOCK_S ? FORMATIONS : EARLY_FORMATIONS;

    let purchases = 0;
    let haulers = 0;

    while (budget >= COST.scout && purchases < maxPurchases) {
        // Throughput guard: stop feeding a screen that's already saturated.
        // Without this a late wave can drain CAP_ENEMY and tank the framerate.
        if (game.pools.enemies.count >= MAX_LIVE_ENEMIES) break;

        // Pick the richest affordable enemy, weighted by depth.
        let type = "scout";
        if (
            canHauler
            && haulers < MAX_HAULERS_PER_WAVE
            && budget >= COST.hauler
            && game.rng.chance(HAULER_CHANCE)
        ) {
            type = "hauler";
        } else if (canSkiff && budget >= COST.skiff && game.rng.chance(SKIFF_CHANCE)) {
            type = "skiff";
        }

        budget -= COST[type];
        purchases++;
        if (type === "hauler") haulers++;

        // Group size + formation. Haulers arrive alone; they're a wall, not a swarm.
        const formation = game.rng.pick(formationPool);
        const count = type === "hauler" ? 1 : game.rng.int(groupMin, groupMax);
        formation(game, type, count);
    }
}
