// Spawn formations. Each lays a group of one enemy type onto the field in a
// recognizable shape. All randomness uses game.rng for determinism.

import { VW } from "./const.js";
import { spawnEnemy } from "./enemies.js";

export function vFormation(game, type, count) {
    const cx = 40 + game.rng.range(0, VW - 80);
    const gap = 18;
    const half = Math.floor(count / 2);
    for (let i = 0; i < count; i++) {
        const off = i - half;
        const x = Math.max(12, Math.min(VW - 12, cx + off * gap));
        const y = -12 - Math.abs(off) * 14;
        spawnEnemy(game, type, x, y);
    }
}

export function pincer(game, type, count) {
    const per = Math.max(1, Math.floor(count / 2));
    for (let i = 0; i < per; i++) {
        spawnEnemy(game, type, 16, -12 - i * 16);
        spawnEnemy(game, type, VW - 16, -12 - i * 16);
    }
}

export function centerRush(game, type, count) {
    const cx = VW / 2 + game.rng.range(-30, 30);
    for (let i = 0; i < count; i++) {
        spawnEnemy(game, type, cx, -12 - i * 16);
    }
}

export const FORMATIONS = [vFormation, pincer, centerRush];
