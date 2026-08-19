// Heads-up display drawn directly onto the 480x360 buffer each frame.

import { VW, BOUNTY_SCORE_MULT } from "./const.js";
import { WEAPONS } from "./weapons.js";

export function drawHud(ctx, game) {
    const p = game.player;
    ctx.save();
    ctx.font = "9px 'Courier New', monospace";
    ctx.textBaseline = "top";

    // Hull (top-left)
    for (let i = 0; i < p.maxHull; i++) {
        ctx.fillStyle = i < p.hull ? "#ff5b5b" : "#3a2030";
        ctx.fillRect(6 + i * 11, 6, 8, 8);
    }
    if (p.shield) {
        ctx.fillStyle = "#37d6ff";
        ctx.fillText("SHLD", 6, 18);
    }

    // EMP charges (top-left, second row)
    ctx.fillStyle = "#ffd83b";
    ctx.fillText("EMP", 66, 6);
    for (let i = 0; i < p.emp; i++) {
        ctx.fillStyle = "#ffd83b";
        ctx.fillRect(93 + i * 8, 6, 5, 8);
    }

    // Weapon + tier (top-left, third row)
    ctx.fillStyle = "#37d6ff";
    const wn = WEAPONS[game.weapon.type].name.split(" ")[0].toUpperCase();
    ctx.fillText(`${wn} T${game.weapon.tier}`, 6, 30);

    // Score + distance + credits (top-right)
    ctx.textAlign = "right";
    ctx.fillStyle = "#ffffff";
    ctx.fillText(`SCORE ${game.score | 0}`, VW - 6, 6);
    ctx.fillStyle = "#9fd0ff";
    ctx.fillText(`${game.distanceM | 0}m`, VW - 6, 18);
    ctx.fillStyle = "#ffd83b";
    ctx.fillText(`${game.credits | 0}cr`, VW - 6, 30);
    ctx.textAlign = "left";

    // Bounty multiplier banner
    if (game.bountyMs > 0) {
        ctx.fillStyle = "#ffbf00";
        ctx.textAlign = "center";
        // Reads BOUNTY_SCORE_MULT directly instead of a hardcoded "x2" -- the
        // old literal would silently go stale the moment const.js is retuned.
        // BOUNTY_SCORE_MULT and BOUNTY_CREDIT_MULT are currently equal, so a
        // single number is accurate for both; if they're ever tuned to differ,
        // this display needs an actual redesign (two numbers), not a bigger
        // string -- that's out of scope here since there's no such tuning yet.
        ctx.fillText(`x${BOUNTY_SCORE_MULT} BOUNTY ${(game.bountyMs / 1000).toFixed(1)}s`, VW / 2, 6);
        ctx.textAlign = "left";
    }

    // Boss health bar
    if (game.boss && game.boss._alive) {
        const frac = Math.max(0, game.boss.hp / game.boss.maxHp);
        ctx.fillStyle = "#3a0000";
        ctx.fillRect(60, 21, VW - 120, 5);
        ctx.fillStyle = "#ff3b3b";
        ctx.fillRect(60, 21, (VW - 120) * frac, 5);
    }

    // Transient wave banner
    if (game.banner && game.bannerMs > 0) {
        ctx.textAlign = "center";
        ctx.fillStyle = "#37d6ff";
        ctx.font = "12px 'Courier New', monospace";
        ctx.fillText(game.banner, VW / 2, 45);
        ctx.textAlign = "left";
    }

    ctx.restore();
}
