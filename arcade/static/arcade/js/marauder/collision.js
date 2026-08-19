// Axis-aligned bounding-box overlap tests. Entities carry center (x,y) + w/h.

export function aabb(a, b) {
    return (
        Math.abs(a.x - b.x) * 2 < a.w + b.w &&
        Math.abs(a.y - b.y) * 2 < a.h + b.h
    );
}

// Circle-ish hit test used for the player (center + radius) vs a box entity.
export function hitsPlayer(player, b) {
    const r = player.radius + Math.max(b.w, b.h) * 0.4;
    const dx = player.x - b.x;
    const dy = player.y - b.y;
    return dx * dx + dy * dy < r * r;
}
