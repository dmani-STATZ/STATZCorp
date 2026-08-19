// Canvas setup: a native 320x240 buffer drawn with nearest-neighbor scaling,
// integer-upscaled and letterboxed to fill the stage. Also maps pointer
// coordinates from screen space into the 320x240 world.

import { VW, VH } from "./const.js";

export function setupCanvas() {
    const canvas = document.getElementById("mar-canvas");
    const stage = document.getElementById("mar-stage");
    const ctx = canvas.getContext("2d");
    ctx.imageSmoothingEnabled = false;

    const api = {
        canvas,
        ctx,
        scale: 1,
        offsetX: 0,
        offsetY: 0,
        // Convert a DOM clientX/clientY to world (0..VW, 0..VH) coords.
        toWorld(clientX, clientY) {
            const rect = canvas.getBoundingClientRect();
            const x = ((clientX - rect.left) / rect.width) * VW;
            const y = ((clientY - rect.top) / rect.height) * VH;
            return { x: Math.max(0, Math.min(VW, x)), y: Math.max(0, Math.min(VH, y)) };
        },
    };

    function resize() {
        const rect = stage.getBoundingClientRect();
        const scale = Math.max(1, Math.floor(Math.min(rect.width / VW, rect.height / VH)));
        api.scale = scale;
        // Backing store stays 320x240; CSS scales it up crisply.
        canvas.style.width = VW * scale + "px";
        canvas.style.height = VH * scale + "px";
        ctx.imageSmoothingEnabled = false;
    }

    window.addEventListener("resize", resize);
    resize();
    return api;
}
