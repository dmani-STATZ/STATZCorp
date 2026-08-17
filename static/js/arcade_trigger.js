(function () {
    'use strict';

    const REQUIRED_CLICKS = 5;
    const WINDOW_MS = 10000;

    document.addEventListener('DOMContentLoaded', function () {
        const trigger = document.getElementById('build-number');
        if (!trigger) return;

        const script = document.querySelector('script[data-arcade-url]');
        const arcadeUrl = script ? script.dataset.arcadeUrl : '/arcade/';

        let clicks = 0;
        let firstClickAt = 0;

        function reset() {
            clicks = 0;
            firstClickAt = 0;
        }

        trigger.addEventListener('click', function () {
            const now = Date.now();
            // Restart the streak if the 10s window from the first click has expired.
            if (clicks === 0 || now - firstClickAt > WINDOW_MS) {
                clicks = 1;
                firstClickAt = now;
                return;
            }
            clicks++;
            if (clicks >= REQUIRED_CLICKS) {
                reset();
                window.location.href = arcadeUrl;
            }
        });

        // Any click elsewhere breaks the streak, so the clicks must be consecutive.
        document.addEventListener('click', function (e) {
            if (!trigger.contains(e.target)) reset();
        }, true);
    });
})();
