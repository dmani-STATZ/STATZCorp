// =============================================================================
// Backyard Marauder — tuning constants.
//
// EVERY number that changes how the game FEELS lives in this file. If you find
// yourself editing a magic number inside a function body, it belongs here
// instead. Native render surface is 480x360, integer-upscaled (3x = 1440x1080
// on a 1920x1080 monitor — readable HUD, pixel-crisp sprites).
//
// !! SERVER COUPLING !!
// Constants marked [SERVER] are mirrored in arcade/services_marauder.py, which
// grades submitted runs against physical ceilings derived from them. Change one
// here without changing the other and honest runs start getting flagged.
// =============================================================================


// -----------------------------------------------------------------------------
// Render surface (structural — not a tuning knob)
// -----------------------------------------------------------------------------
export const VW = 480;
export const VH = 360;


// -----------------------------------------------------------------------------
// World scroll  [SERVER: MAX_SCROLL_MPS = SCROLL_MAX / PX_PER_METER]
//
// Speed ramps from SCROLL_BASE and gains SCROLL_GROWTH px/s every second until
// it hits SCROLL_MAX. With the values below that cap lands at 120s:
//     (SCROLL_MAX - SCROLL_BASE) / SCROLL_GROWTH  =  (150 - 42) / 0.9  =  120s
// Past that the world speed is FLAT by design — the director carries the ramp
// from there (see WAVE_* below). Raise SCROLL_MAX and you must raise
// MAX_SCROLL_MPS server-side to match.
// NOTE: scroll speeds are world-space px/s — they do not need adjusting when
// VW/VH changes; only the CSS upscale factor changes.
// -----------------------------------------------------------------------------
export const SCROLL_BASE = 42;          // px/sec at run start
export const SCROLL_GROWTH = 0.9;       // extra px/sec per second elapsed
export const SCROLL_MAX = 150;          // px/sec cap  [SERVER]
export const PX_PER_METER = 4;          // [SERVER] — do not change casually


// -----------------------------------------------------------------------------
// Scoring  [SERVER: score ceiling = SCORE_PER_METER * BOUNTY_SCORE_MULT * distance]
//
// SCORE_PER_METER was 1, which made distance almost worthless: a single 1500pt
// Enforcer kill was worth 1500 meters of flawless survival (~40+ seconds), so
// there was never a reason to prioritize staying alive over farming. At 5, a
// boss is worth ~300m and the two strategies actually compete.
//
// Tuning note: raise this to reward survival, lower it to reward aggression.
// -----------------------------------------------------------------------------
export const SCORE_PER_METER = 5;       // [SERVER]
export const BOUNTY_SCORE_MULT = 2;     // [SERVER] — score multiplier while bounty is up
export const BOUNTY_CREDIT_MULT = 2;    // credit multiplier while bounty is up
export const BOUNTY_MS = 10000;         // how long a bounty pickup lasts


// -----------------------------------------------------------------------------
// Player feel
//
// STIFFNESS/DAMPING drive the mouse-follow spring and are the highest-leverage
// numbers in the game. They used to be hardcoded locals in main.js.
//   - Raise STIFFNESS  -> ship snaps to the cursor harder (twitchier)
//   - Raise DAMPING    -> less overshoot / wobble (heavier, more planted)
// Roughly: stiffness/damping ~7 is floaty, ~13 is planted. Tune together.
// -----------------------------------------------------------------------------
export const PLAYER_STIFFNESS = 95;
export const PLAYER_DAMPING = 13;
export const PLAYER_MAX_HULL = 5;
export const PLAYER_START_EMP = 2;
export const PLAYER_RADIUS = 5;         // collision radius (structural-ish)
export const PLAYER_INVULN_MS = 1200;   // i-frames after taking a hit
export const START_Y = VH - 60;


// -----------------------------------------------------------------------------
// Director / waves  [SERVER: MAX_KILLS_PER_SEC is derived from wave throughput]
//
// Every WAVE_INTERVAL seconds the director allocates a threat budget and spends
// it "buying" enemy formations. THREE dials control the ramp:
//
//   1. THREAT_*         — how much it can afford (gates enemy MIX early on)
//   2. WAVE_PURCHASE_*  — how many formations one wave may spawn (the SIZE ramp)
//   3. WAVE_INTERVAL_*  — how often waves arrive (the PRESSURE ramp)
//
// The old build had a hardcoded cap of 12 purchases, so past ~36s the budget
// was decoration and difficulty went flat. Worse, rolling a hauler ended the
// wave outright, so waves got *smaller* the moment haulers unlocked at 45s.
// Both are fixed; these are the dials that replaced them.
// -----------------------------------------------------------------------------
export const WAVE_INTERVAL = 5.0;         // seconds between waves at run start
export const WAVE_INTERVAL_MIN = 1.6;     // floor — waves never come faster
export const WAVE_INTERVAL_DECAY = 0.012; // seconds shaved per second elapsed
                                          // (hits the floor at ~283s)

// THREAT_BASE stays at 2 from the previous pass -- WAVE_PURCHASE_BASE below is
// now the binding constraint on wave size from t=0 onward (2 budget covers far
// more than 1 purchase's worth of scouts), so tuning THREAT_BASE further would
// have no visible effect on the opening.
export const THREAT_BASE = 2;             // budget at t=0
export const THREAT_SCALING = 0.9;        // extra budget per second elapsed

// WAVE_PURCHASE_BASE: 10 -> 1. Playtest feedback: even after the previous
// pass, wave 1 (~9 enemies, still budget-limited rather than purchase-
// limited) felt unreachable -- multiple independently-positioned formations
// spawned in the same wave, spread across the full screen width, faster than
// a player can physically cover 320px of lateral distance. At BASE=1,
// purchase count (not budget) becomes the binding constraint from wave 1:
//   t=5s   (wave 1): 1 purchase  -> 1-2 enemies   (was ~9)
//   t=25s:           2 purchases -> 2-4 enemies
//   t=50s:           3 purchases -> 3-6 enemies
//   t=225s:          10 purchases (matches the OLD flat WAVE_PURCHASE_BASE)
//   t=475s:          20 purchases (WAVE_PURCHASE_CAP, unchanged) -- was ~250s
// The ramp to full intensity now takes roughly twice as long. That's
// deliberate, not a side effect: "start real easy, get comfortable, then ramp
// up" means the whole curve stretches, not just the first wave.
export const WAVE_PURCHASE_BASE = 1;      // formations per wave at t=0
export const WAVE_PURCHASE_GROWTH = 0.04; // extra formations per second elapsed
export const WAVE_PURCHASE_CAP = 20;      // hard ceiling (hits it at ~475s now)

export const MAX_HAULERS_PER_WAVE = 2;    // was effectively 1-and-end-the-wave
export const MAX_LIVE_ENEMIES = 64;       // throughput guard; keep < CAP_ENEMY (96)
// The director stops buying new formations once the live count exceeds
// SPAWN_SOFT_CAP_FRAC * MAX_LIVE_ENEMIES (~51). This lets the screen thin out
// naturally rather than packing to a wall, while the hard MAX_LIVE_ENEMIES cap
// in spawnEnemy() still prevents runaway accumulation.
export const SPAWN_SOFT_CAP_FRAC = 0.80;

// Formation size ramps from (BASE) at t=0 to (FINAL) by GROUP_RAMP_SECONDS,
// then holds at FINAL for the rest of the run. FINAL values equal the old
// flat constants exactly, so nothing about gameplay past GROUP_RAMP_SECONDS
// changes on this axis. Left as-is from the previous pass -- not implicated
// in this round's feedback, and WAVE_PURCHASE_BASE above is now doing most of
// the work on headcount.
export const GROUP_MIN_BASE = 1;          // formation size at t=0
export const GROUP_MAX_BASE = 2;
export const GROUP_MIN_FINAL = 3;         // == old GROUP_MIN
export const GROUP_MAX_FINAL = 5;         // == old GROUP_MAX
export const GROUP_RAMP_SECONDS = 90;     // time to reach FINAL group sizes

export const SKIFF_UNLOCK_S = 20;         // seconds before skiffs appear
export const HAULER_UNLOCK_S = 45;        // seconds before haulers appear
export const SKIFF_CHANCE = 0.5;          // roll per purchase, once unlocked
export const HAULER_CHANCE = 0.2;

// pincer (formations.js) spawns at BOTH screen edges (x=16 and x=VW-16)
// simultaneously, unconditionally -- by construction it is the one formation
// shape that guarantees enemies on opposite sides of the screen at the same
// time. That is a fair, deliberate challenge once a player has room to
// maneuver, but it is exactly the mechanic behind "enemies spread across the
// entire screen, a player can't shoot all of them" during the opening.
// Excluded from the formation pool (see director.js's EARLY_FORMATIONS use)
// until PINCER_UNLOCK_S.
export const PINCER_UNLOCK_S = 20;        // matches SKIFF_UNLOCK_S

export const BOSS_EVERY_M = 1500;         // Corporate Enforcer cadence, in meters
                                          // (first boss lands at ~78s)
// When the boss milestone is reached, the director halts normal wave spawning
// and waits up to BOSS_CLEAR_WAIT_S seconds for the player to thin the field.
// If live enemies drop to BOSS_CLEAR_THRESHOLD first, the boss drops immediately
// (reward for aggressive play). Either way, the boss never stacks on top of a
// full screen of fodder.
export const BOSS_CLEAR_WAIT_S = 8;       // max pre-boss quiet window (seconds)
export const BOSS_CLEAR_THRESHOLD = 5;    // enemy count that ends the wait early

// -----------------------------------------------------------------------------
// Loot drop rate  [independent of the difficulty ramps above]
//
// "high"/"boss" tier loot (haulers, the Enforcer) always drops -- unconditional
// in powerups.js, unaffected by anything here. "low" tier (scouts -- the only
// enemy present in the true opening) drops on a flat percentage roll per kill.
// The old flat 8% meant most players got zero crates across their first
// couple of waves, directly contradicting "give the player power-ups before
// we start to overwhelm them." Ramps from BASE down to FINAL (the old flat
// value, so late-game loot scarcity/economy is unchanged) over
// LOOT_RAMP_SECONDS, chosen SHORTER than the difficulty ramps above so
// generosity front-loads ahead of difficulty, not merely alongside it.
// -----------------------------------------------------------------------------
export const LOW_LOOT_CHANCE_BASE = 0.4;   // per-kill crate chance at t=0
export const LOW_LOOT_CHANCE_FINAL = 0.08; // == old flat chance, unchanged
export const LOOT_RAMP_SECONDS = 60;       // time to decay to FINAL


// -----------------------------------------------------------------------------
// Pool capacities (structural — raise only if you see entities failing to spawn)
// -----------------------------------------------------------------------------
export const CAP_PBULLET = 256;
export const CAP_EBULLET = 512;
export const CAP_ENEMY = 96;
export const CAP_POWERUP = 32;
export const CAP_PARTICLE = 384;

// NOTE: PLAYER_ACCEL, FACTION_PLAYER and FACTION_ENEMY were removed here —
// they were declared but imported by nothing. PLAYER_ACCEL in particular was
// a decoy: the real movement feel is PLAYER_STIFFNESS / PLAYER_DAMPING above.
