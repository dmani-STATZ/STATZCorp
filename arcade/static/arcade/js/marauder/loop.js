// Fixed-timestep game loop. Logic runs at a deterministic 60Hz; render receives
// an interpolation alpha. Clamps large deltas (tab throttle) to avoid a spiral
// of death, and skips accumulation while the tab is hidden.

const STEP_MS = 1000 / 60;

export function createLoop(update, render) {
    let acc = 0;
    let last = performance.now();
    let raf = null;
    let running = false;

    function frame(now) {
        if (!running) return;
        let delta = now - last;
        last = now;
        if (delta > 250) delta = 250;
        acc += delta;
        while (acc >= STEP_MS) {
            update(STEP_MS / 1000);
            acc -= STEP_MS;
        }
        render(acc / STEP_MS);
        raf = requestAnimationFrame(frame);
    }

    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) last = performance.now(); // don't fast-forward
    });

    return {
        start() {
            if (running) return;
            running = true;
            last = performance.now();
            acc = 0;
            raf = requestAnimationFrame(frame);
        },
        stop() {
            running = false;
            if (raf) cancelAnimationFrame(raf);
            raf = null;
        },
        get running() { return running; },
    };
}
