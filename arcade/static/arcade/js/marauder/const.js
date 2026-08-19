// =============================================================================
// Backyard Marauder — tuning constants.
//
// EVERY number that changes how the game FEELS lives in this file. If you find
// yourself editing a magic number inside a function body, it belongs here
// instead. Native render surface is 320x240, integer-upscaled.
//
// !! SERVER COUPLING !!
// Constants marked [SERVER] are mirrored in arcade/services_marauder.py, which
// grades submitted runs against physical ceilings derived from them. Change one
// here without changing the other and honest runs start getting flagged.
// =============================================================================


// -----------------------------------------------------------------------------
// Render surface (structural — not a tuning knob)
// -----------------------------------------------------------------------------
export const VW = 320;
export const VH = 240;


// -----------------------------------------------------------------------------
// World scroll  [SERVER: MAX_SCROLL_MPS = SCROLL_MAX / PX_PER_METER]
//
// Speed ramps from SCROLL_BASE and gains SCROLL_GROWTH px/s every second until
// it hits SCROLL_MAX. With the values below that cap lands at 120s:
//     (SCROLL_MAX - SCROLL_BASE) / SCROLL_GROWTH  =  (150 - 42) / 0.9  =  120s
// Past that the world speed is FLAT by design — the director carries the ramp
// from there (see WAVE_* below). Raise SCROLL_MAX and you must raise
// MAX_SCROLL_MPS server-side to match.
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
export const START_Y = VH - 40;


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

export const THREAT_BASE = 4;             // budget at t=0
export const THREAT_SCALING = 0.9;        // extra budget per second elapsed

export const WAVE_PURCHASE_BASE = 10;     // formations per wave at t=0
export const WAVE_PURCHASE_GROWTH = 0.04; // extra formations per second elapsed
export const WAVE_PURCHASE_CAP = 20;      // hard ceiling (hits it at ~250s)

export const MAX_HAULERS_PER_WAVE = 2;    // was effectively 1-and-end-the-wave
export const MAX_LIVE_ENEMIES = 48;       // throughput guard; keep < CAP_ENEMY

export const GROUP_MIN = 3;               // formation size for scouts/skiffs
export const GROUP_MAX = 5;

export const SKIFF_UNLOCK_S = 20;         // seconds before skiffs appear
export const HAULER_UNLOCK_S = 45;        // seconds before haulers appear
export const SKIFF_CHANCE = 0.5;          // roll per purchase, once unlocked
export const HAULER_CHANCE = 0.2;

export const BOSS_EVERY_M = 1500;         // Corporate Enforcer cadence, in meters
                                          // (first boss lands at ~78s)


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
