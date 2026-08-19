// Canvas setup: a native 320x240 buffer drawn with nearest-neighbor scaling,
// integer-upscaled and letterboxed to fill the stage. Also maps pointer
// coordinates from screen space into the 320x240 world.
//
// Uses a ResizeObserver on #mar-stage instead of only listening for the
// window's `resize` event. The old code measured the stage's size exactly
// once, synchronously, when this module first ran, then only re-measured on
// an actual browser window resize. If that one measurement landed before the
// page's layout had fully settled (a web font swapping in, a flex/grid
// container not yet resolved, etc.), the stage's rect could read back small
// or zero -- and since `scale` is floored with a minimum of 1, a bad
// measurement doesn't degrade to a smaller-but-sane scale, it collapses
// straight to the raw unscaled 320x240 canvas, permanently, because nothing
// ever re-measured it afterward. ResizeObserver fires on every real size
// change of the observed element for any reason, including layout settling
// after the initial paint, so this can no longer get stuck.

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

    if (window.ResizeObserver) {
        // Fires immediately on observe() with the current size, then again on
        // every subsequent real size change -- covers the initial-layout-not-
        // settled case AND ordinary window resizes AND any later reflow
        // (sidebar toggle, font swap, orientation change) with one mechanism.
        const ro = new ResizeObserver(resize);
        ro.observe(stage);
    } else {
        // Fallback for the rare browser without ResizeObserver support. Not
        // expected to matter in practice -- this project already assumes
        // native ES modules, which have equal-or-broader support -- but the
        // fallback is two lines and costs nothing to keep.
        window.addEventListener("resize", resize);
        resize();
    }

    return api;
}
