// Input: mouse-follow target, hold-to-fire (left button), EMP trigger
// (right click / spacebar). Exposes a per-frame snapshot on `input`.

import { VW, VH, START_Y } from "./const.js";

export function setupInput(view) {
    const input = {
        targetX: VW / 2,
        targetY: START_Y,
        firing: false,
        empQueued: false,   // consumed by the game loop
        hasPointer: false,
    };

    const canvas = view.canvas;

    canvas.addEventListener("mousemove", (e) => {
        const w = view.toWorld(e.clientX, e.clientY);
        input.targetX = w.x;
        input.targetY = w.y;
        input.hasPointer = true;
    });

    canvas.addEventListener("mousedown", (e) => {
        if (e.button === 0) input.firing = true;
        if (e.button === 2) { input.empQueued = true; e.preventDefault(); }
    });
    window.addEventListener("mouseup", (e) => {
        if (e.button === 0) input.firing = false;
    });
    canvas.addEventListener("contextmenu", (e) => e.preventDefault());

    // Touch: drag to move, tap fires.
    canvas.addEventListener("touchmove", (e) => {
        const t = e.touches[0];
        if (!t) return;
        const w = view.toWorld(t.clientX, t.clientY);
        input.targetX = w.x;
        input.targetY = w.y;
        input.firing = true;
        input.hasPointer = true;
        e.preventDefault();
    }, { passive: false });
    canvas.addEventListener("touchstart", (e) => {
        const t = e.touches[0];
        if (t) { const w = view.toWorld(t.clientX, t.clientY); input.targetX = w.x; input.targetY = w.y; }
        input.firing = true;
        input.hasPointer = true;
    });
    canvas.addEventListener("touchend", () => { input.firing = false; });

    window.addEventListener("keydown", (e) => {
        if (e.code === "Space") { input.empQueued = true; e.preventDefault(); }
    });

    return input;
}
