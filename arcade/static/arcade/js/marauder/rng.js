// Seeded PRNG (mulberry32). ALL gameplay randomness flows through this so a run
// is reproducible from the server-issued seed (enables future re-simulation).

function xmur3(str) {
    let h = 1779033703 ^ str.length;
    for (let i = 0; i < str.length; i++) {
        h = Math.imul(h ^ str.charCodeAt(i), 3432918353);
        h = (h << 13) | (h >>> 19);
    }
    return function () {
        h = Math.imul(h ^ (h >>> 16), 2246822507);
        h = Math.imul(h ^ (h >>> 13), 3266489909);
        h ^= h >>> 16;
        return h >>> 0;
    };
}

export function makeRng(seedStr) {
    const seedFn = xmur3(String(seedStr || "marauder"));
    let a = seedFn();
    // mulberry32
    const next = function () {
        a |= 0;
        a = (a + 0x6d2b79f5) | 0;
        let t = Math.imul(a ^ (a >>> 15), 1 | a);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    return {
        next,                                   // [0,1)
        range: (lo, hi) => lo + next() * (hi - lo),
        int: (lo, hi) => Math.floor(lo + next() * (hi - lo + 1)),
        pick: (arr) => arr[Math.floor(next() * arr.length)],
        chance: (p) => next() < p,
    };
}
