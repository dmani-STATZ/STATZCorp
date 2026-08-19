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
    MAX_HAULERS_PER_WAVE, MAX_LIVE_ENEMIES, SPAWN_SOFT_CAP_FRAC,
    GROUP_MIN_BASE, GROUP_MAX_BASE, GROUP_MIN_FINAL, GROUP_MAX_FINAL, GROUP_RAMP_SECONDS,
    SKIFF_UNLOCK_S, HAULER_UNLOCK_S, SKIFF_CHANCE, HAULER_CHANCE,
    PINCER_UNLOCK_S, BOSS_EVERY_M, BOSS_CLEAR_WAIT_S, BOSS_CLEAR_THRESHOLD,
} from "./const.js";
import { FORMATIONS, EARLY_FORMATIONS } from "./formations.js";
import { spawnEnemy } from "./enemies.js";

const COST = { scout: 1, skiff: 3, hauler: 8 };

// Soft cap: stop buying new formations once live count exceeds this.
// Allows enemies to thin out naturally instead of packing to a wall.
// The hard MAX_LIVE_ENEMIES in spawnEnemy() is the absolute backstop.
const SPAWN_SOFT_CAP = Math.floor(MAX_LIVE_ENEMIES * SPAWN_SOFT_CAP_FRAC);

export function createDirector() {
    return {
        timer: WAVE_INTERVAL,
        wave: 0,
        nextBossM: BOSS_EVERY_M,
        bossActive: false,
        // Pre-boss quiet period: when the milestone is hit we pause normal waves
        // and give the player BOSS_CLEAR_WAIT_S seconds to thin the field.
        preBoss: false,       // true while we're in the quiet window
        preBossTimer: 0,      // counts down; boss drops when this hits 0 or
                              // when live enemies <= BOSS_CLEAR_THRESHOLD
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

    // ---- Pre-boss quiet period ------------------------------------------------
    // When distanceM crosses the boss milestone we stop spawning regular waves
    // and wait up to BOSS_CLEAR_WAIT_S seconds. This gives the player a moment
    // to clear the screen before the Enforcer drops. Aggressive players who
    // kill down to BOSS_CLEAR_THRESHOLD get the boss immediately as a reward.
    if (d.preBoss && !d.bossActive) {
        d.preBossTimer -= dt;
        const fieldClear = game.pools.enemies.count <= BOSS_CLEAR_THRESHOLD;
        if (d.preBossTimer <= 0 || fieldClear) {
            const boss = spawnEnemy(game, "enforcer", VW / 2, -30);
            if (boss) {
                d.preBoss = false;
                d.preBossTimer = 0;
                d.nextBossM += BOSS_EVERY_M;
                game.wave++;
                if (game.audio) game.audio.sfx("boss");
            }
            // If the pool was somehow full (very unlikely during quiet), retry
            // next tick without consuming more of the timer.
        }
        return; // no normal waves while pre-boss or boss is alive
    }

    // ---- Boss milestone check -------------------------------------------------
    // Trigger the quiet period; do NOT spawn the boss immediately.
    if (!d.bossActive && !d.preBoss && game.distanceM >= d.nextBossM) {
        d.preBoss = true;
        d.preBossTimer = BOSS_CLEAR_WAIT_S;
        game.banner = "ENFORCER INBOUND";
        game.bannerMs = BOSS_CLEAR_WAIT_S;
        return;
    }

    // Hold off new waves while a boss is alive — the Enforcer is a duel.
    if (d.bossActive) return;

    // ---- Wave timer ----------------------------------------------------------
    d.timer -= dt;
    if (d.timer > 0) return;
    d.timer = waveInterval(game.elapsed);
    d.wave++;
    game.wave = Math.max(game.wave, d.wave);

    // ---- Spend the threat budget --------------------------------------------
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
        // Soft throughput guard: stop buying once screen is 80% full, letting
        // enemies drain before the next wave fills it completely. The hard
        // MAX_LIVE_ENEMIES guard in spawnEnemy() is the absolute backstop.
        if (game.pools.enemies.count >= SPAWN_SOFT_CAP) break;

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
