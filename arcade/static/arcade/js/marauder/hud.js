// Heads-up display drawn directly onto the 320x240 buffer each frame.

import { VW } from "./const.js";
import { WEAPONS } from "./weapons.js";

export function drawHud(ctx, game) {
    const p = game.player;
    ctx.save();
    ctx.font = "6px 'Courier New', monospace";
    ctx.textBaseline = "top";

    // Hull (top-left)
    for (let i = 0; i < p.maxHull; i++) {
        ctx.fillStyle = i < p.hull ? "#ff5b5b" : "#3a2030";
        ctx.fillRect(4 + i * 7, 4, 5, 5);
    }
    if (p.shield) {
        ctx.fillStyle = "#37d6ff";
        ctx.fillText("SHLD", 4, 12);
    }

    // EMP charges (top-left, second row)
    ctx.fillStyle = "#ffd83b";
    ctx.fillText("EMP", 44, 4);
    for (let i = 0; i < p.emp; i++) {
        ctx.fillStyle = "#ffd83b";
        ctx.fillRect(62 + i * 5, 4, 3, 5);
    }

    // Weapon + tier (top-left, third row)
    ctx.fillStyle = "#37d6ff";
    const wn = WEAPONS[game.weapon.type].name.split(" ")[0].toUpperCase();
    ctx.fillText(`${wn} T${game.weapon.tier}`, 4, 20);

    // Score + distance + credits (top-right)
    ctx.textAlign = "right";
    ctx.fillStyle = "#ffffff";
    ctx.fillText(`SCORE ${game.score | 0}`, VW - 4, 4);
    ctx.fillStyle = "#9fd0ff";
    ctx.fillText(`${game.distanceM | 0}m`, VW - 4, 12);
    ctx.fillStyle = "#ffd83b";
    ctx.fillText(`${game.credits | 0}cr`, VW - 4, 20);
    ctx.textAlign = "left";

    // Bounty multiplier banner
    if (game.bountyMs > 0) {
        ctx.fillStyle = "#ffbf00";
        ctx.textAlign = "center";
        ctx.fillText(`x2 BOUNTY ${(game.bountyMs / 1000).toFixed(1)}s`, VW / 2, 4);
        ctx.textAlign = "left";
    }

    // Boss health bar
    if (game.boss && game.boss._alive) {
        const frac = Math.max(0, game.boss.hp / game.boss.maxHp);
        ctx.fillStyle = "#3a0000";
        ctx.fillRect(40, 14, VW - 80, 3);
        ctx.fillStyle = "#ff3b3b";
        ctx.fillRect(40, 14, (VW - 80) * frac, 3);
    }

    // Transient wave banner
    if (game.banner && game.bannerMs > 0) {
        ctx.textAlign = "center";
        ctx.fillStyle = "#37d6ff";
        ctx.font = "8px 'Courier New', monospace";
        ctx.fillText(game.banner, VW / 2, 30);
        ctx.textAlign = "left";
    }

    ctx.restore();
}
