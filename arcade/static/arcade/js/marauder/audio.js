// WebAudio chiptune + SFX engine. No audio files — everything is synthesized.
// AudioContext is created lazily and resumed on the first user gesture.

const NOTE = {}; // name -> frequency
(function buildNotes() {
    const names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
    for (let oct = 1; oct <= 6; oct++) {
        for (let i = 0; i < 12; i++) {
            const n = 12 * (oct - 1) + i;
            NOTE[names[i] + oct] = 55 * Math.pow(2, (n - 9) / 12); // A1=55Hz anchor
        }
    }
})();

// Simple bass + lead loop (16 steps). Square-wave chiptune.
const BASS = ["A2", "A2", "E2", "E2", "F2", "F2", "C2", "G2",
              "A2", "A2", "E2", "E2", "F2", "G2", "A2", "A2"];
const LEAD = ["A4", null, "C5", "E5", "A4", null, "G4", "E4",
              "F4", null, "A4", "C5", "E5", "D5", "C5", null];

export function createAudio() {
    let ctx = null;
    let master = null;
    let musicGain = null;
    let muted = false;
    let step = 0;
    let nextTime = 0;
    let timer = null;
    const STEP_DUR = 0.14;
    const LOOKAHEAD = 0.1;

    function ensure() {
        if (ctx) return;
        const AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) return;
        ctx = new AC();
        master = ctx.createGain();
        master.gain.value = 0.5;
        master.connect(ctx.destination);
        musicGain = ctx.createGain();
        musicGain.gain.value = 0.18;
        musicGain.connect(master);
    }

    function resume() {
        ensure();
        if (ctx && ctx.state === "suspended") ctx.resume();
    }

    function blip(freq, dur, type, gainVal, dest) {
        if (!ctx || muted) return;
        const o = ctx.createOscillator();
        const g = ctx.createGain();
        o.type = type;
        o.frequency.value = freq;
        g.gain.setValueAtTime(gainVal, ctx.currentTime);
        g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + dur);
        o.connect(g);
        g.connect(dest || master);
        o.start();
        o.stop(ctx.currentTime + dur);
    }

    function noise(dur, gainVal, freq) {
        if (!ctx || muted) return;
        const n = Math.floor(ctx.sampleRate * dur);
        const buf = ctx.createBuffer(1, n, ctx.sampleRate);
        const data = buf.getChannelData(0);
        for (let i = 0; i < n; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / n);
        const src = ctx.createBufferSource();
        src.buffer = buf;
        const g = ctx.createGain();
        g.gain.value = gainVal;
        const lp = ctx.createBiquadFilter();
        lp.type = "lowpass";
        lp.frequency.value = freq || 1200;
        src.connect(lp); lp.connect(g); g.connect(master);
        src.start();
    }

    function scheduleAt(name, t) {
        // bass
        const b = BASS[step % BASS.length];
        if (b && NOTE[b]) {
            const o = ctx.createOscillator();
            const g = ctx.createGain();
            o.type = "square";
            o.frequency.value = NOTE[b];
            g.gain.setValueAtTime(0.5, t);
            g.gain.exponentialRampToValueAtTime(0.0001, t + STEP_DUR * 0.9);
            o.connect(g); g.connect(musicGain);
            o.start(t); o.stop(t + STEP_DUR);
        }
        const l = LEAD[step % LEAD.length];
        if (l && NOTE[l]) {
            const o = ctx.createOscillator();
            const g = ctx.createGain();
            o.type = "square";
            o.frequency.value = NOTE[l];
            g.gain.setValueAtTime(0.28, t);
            g.gain.exponentialRampToValueAtTime(0.0001, t + STEP_DUR * 0.8);
            o.connect(g); g.connect(musicGain);
            o.start(t); o.stop(t + STEP_DUR);
        }
    }

    function tick() {
        if (!ctx) return;
        while (nextTime < ctx.currentTime + LOOKAHEAD) {
            scheduleAt(step, nextTime);
            nextTime += STEP_DUR;
            step++;
        }
    }

    return {
        resume,
        startMusic() {
            ensure(); resume();
            if (!ctx || timer) return;
            step = 0;
            nextTime = ctx.currentTime + 0.05;
            timer = setInterval(tick, 25);
        },
        stopMusic() {
            if (timer) { clearInterval(timer); timer = null; }
        },
        sfx(name) {
            if (!ctx || muted) return;
            switch (name) {
                case "shoot":     blip(880, 0.06, "square", 0.08); break;
                case "explosion": noise(0.3, 0.5, 900); break;
                case "hit":       blip(120, 0.18, "square", 0.35); noise(0.15, 0.3, 500); break;
                case "pickup":    blip(660, 0.06, "square", 0.2); setTimeout(() => blip(990, 0.08, "square", 0.2), 60); break;
                case "emp":       noise(0.5, 0.6, 2200); blip(220, 0.4, "sawtooth", 0.2); break;
                case "boss":      blip(70, 0.6, "sawtooth", 0.4); break;
                case "gameover":  blip(330, 0.2, "square", 0.3); setTimeout(() => blip(220, 0.4, "square", 0.3), 180); break;
            }
        },
        toggleMute() {
            muted = !muted;
            if (master) master.gain.value = muted ? 0 : 0.5;
            return muted;
        },
        isMuted() { return muted; },
    };
}
