// Entity structs + pools. Entities are plain mutable objects reused by the
// pools; `px/py` hold the previous-frame position for render interpolation.

import { Pool } from "./pool.js";
import {
    VW, START_Y, PLAYER_MAX_HULL, PLAYER_START_EMP, PLAYER_RADIUS,
    CAP_PBULLET, CAP_EBULLET, CAP_ENEMY, CAP_POWERUP, CAP_PARTICLE,
} from "./const.js";

function newBullet() {
    return {
        _alive: false, x: 0, y: 0, px: 0, py: 0, vx: 0, vy: 0,
        w: 2, h: 4, dmg: 1, faction: 0, kind: "bolt",
        homing: false, target: null, life: 4, pierce: 0, color: "#ffd83b",
    };
}
function resetBullet(b) { b.target = null; b.homing = false; b.pierce = 0; }

function newEnemy() {
    return {
        _alive: false, x: 0, y: 0, px: 0, py: 0, vx: 0, vy: 0,
        w: 12, h: 12, hp: 1, maxHp: 1, type: "scout", points: 10, credits: 5,
        fireTimer: 0, fireEvery: 1.5, phase: 0, t: 0, baseX: 0, angle: 0,
        loot: "none", radius: 6,
    };
}
function resetEnemy(e) { e.target = null; }

function newPowerup() {
    return { _alive: false, x: 0, y: 0, px: 0, py: 0, vy: 0, kind: "plating", spin: 0, w: 10, h: 10 };
}

function newParticle() {
    return {
        _alive: false, x: 0, y: 0, px: 0, py: 0, vx: 0, vy: 0,
        life: 0, maxLife: 0.4, color: "#ffd83b", size: 2,
    };
}

export function createPools() {
    return {
        pBullets: new Pool(CAP_PBULLET, newBullet, resetBullet),
        eBullets: new Pool(CAP_EBULLET, newBullet, resetBullet),
        enemies: new Pool(CAP_ENEMY, newEnemy, resetEnemy),
        powerups: new Pool(CAP_POWERUP, newPowerup),
        particles: new Pool(CAP_PARTICLE, newParticle),
    };
}

export function createPlayer() {
    return {
        x: VW / 2, y: START_Y, px: VW / 2, py: START_Y, vx: 0, vy: 0,
        hull: PLAYER_MAX_HULL, maxHull: PLAYER_MAX_HULL, shield: false,
        invulnMs: 0, radius: PLAYER_RADIUS, emp: PLAYER_START_EMP,
        roll: 0, // barrel-roll animation timer
    };
}
