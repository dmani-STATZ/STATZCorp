// Procedural pixel-art sprite factory. Each sprite is authored as a grid of
// characters mapped to palette colors, rendered once to an offscreen canvas and
// cached. No binary assets — everything is generated at load.

const cache = {};

function build(rows, palette) {
    const h = rows.length;
    const w = rows[0].length;
    const c = document.createElement("canvas");
    c.width = w;
    c.height = h;
    const ctx = c.getContext("2d");
    for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
            const ch = rows[y][x];
            const col = palette[ch];
            if (!col) continue;
            ctx.fillStyle = col;
            ctx.fillRect(x, y, 1, 1);
        }
    }
    return c;
}

// . = transparent
const SPRITES = {
    player: {
        rows: [
            "......XX......",
            ".....XCCX.....",
            ".....XCCX.....",
            "....XCBBCX....",
            "...XCBWWBCX...",
            "..GXCBWWBCXG..",
            ".GGXBBWWBBXGG.",
            "GGGXBWWWWBXGGG",
            ".G.XBBWWBBX.G.",
            "...XBRRRRBX...",
            "...XR.RR.RX...",
            "..FF..FF..FF..",
            ".F.F......F.F.",
        ],
        palette: { X: "#0a1030", C: "#37d6ff", B: "#2a5fa8", W: "#dbe8ff", G: "#7fd1ff", R: "#ff6a3b", F: "#ffd83b" },
    },
    scout: {
        rows: [
            "..R....R..",
            ".RRR..RRR.",
            "RRWRRRWRR.",
            ".RRWWWWRR.",
            "..RWKWWR..",
            "...RWWR...",
            "....RR....",
            "...R..R...",
        ],
        palette: { R: "#ff4d4d", W: "#ffd0d0", K: "#3a0000" },
    },
    skiff: {
        rows: [
            "..PPPPPPPP..",
            ".PWWPPPPWWP.",
            "PPWWWWWWWWPP",
            "PGPWKKKKWPGP",
            "PGPWWWWWWPGP",
            ".PPGGGGGGPP.",
            "..P.P..P.P..",
            "..LL....LL..",
        ],
        palette: { P: "#a24dff", W: "#e6d0ff", G: "#6a2fae", K: "#1a0033", L: "#ff8a3b" },
    },
    hauler: {
        rows: [
            "....OOOOOOOOOOOO....",
            "...OYYYYYYYYYYYYO...",
            "..OYSSSSSSSSSSSSYO..",
            ".OYSHHSHHSHHSHHSSYO.",
            "OYSHHSHHSHHSHHSHHSYO",
            "OYSSSSSSSSSSSSSSSSYO",
            "OYSHHSHHSHHSHHSHHSYO",
            ".OYSSSSSSSSSSSSSSYO.",
            "..OYYYYYYYYYYYYYYO..",
            "...OOOO.OOOO.OOOO...",
        ],
        palette: { O: "#5a4a20", Y: "#c8a13a", S: "#8f7326", H: "#e8c85a" },
    },
    enforcer: {
        rows: [
            "......TTTTTTTTTTTTTTTT......",
            "....TTNNNNNNNNNNNNNNNNTT....",
            "..TTNNMMMMMMMMMMMMMMMMNNTT..",
            ".TNNMMCCMMMMMMMMMMCCMMNNT.",
            "TNNMMCCCCMMMMMMMMCCCCMMNNT.",
            "TNMMMCCMMMMRRRRMMMMCCMMMNNT",
            "TNMMMMMMMMRRWWRRMMMMMMMMMNT",
            "TNNMMMMMMMRRWWRRMMMMMMMMNNT",
            ".TNNMMMMMMMRRRRMMMMMMMMNNT.",
            "..TTNNMMMMMMMMMMMMMMMMNNTT.",
            "....TTNNNNNNNNNNNNNNNNTT....",
            "......TTTTTTTTTTTTTTTT......",
        ],
        palette: { T: "#2b2f45", N: "#4a5170", M: "#7c86b8", C: "#37d6ff", R: "#ff3b3b", W: "#ffe0e0" },
    },
    crate: {
        rows: [
            "KKKKKKKK",
            "KWLLLLWK",
            "KLwwwwLK",
            "KLwCCwLK",
            "KLwCCwLK",
            "KLwwwwLK",
            "KWLLLLWK",
            "KKKKKKKK",
        ],
        // 'C' is the accent square, recolored per powerup kind via CRATE_TINT.
        palette: { K: "#1a1a2a", W: "#ffffff", L: "#9aa4c0", w: "#2a3350", C: "#ffd83b" },
    },
};

export function getSprite(key) {
    if (cache[key]) return cache[key];
    const def = SPRITES[key];
    if (!def) return null;
    const c = build(def.rows, def.palette);
    cache[key] = c;
    return c;
}

// Crate accent colors per powerup kind.
export const CRATE_TINT = {
    plating: "#37ff8a",
    overclock: "#ffd83b",
    nuke: "#ff5bd0",
    bounty: "#ffbf00",
};
