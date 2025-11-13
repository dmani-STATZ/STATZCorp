// TD Now - minimal tower defense using canvas and vanilla JS
// - Fetch level config from /td-now/api/levels/1/
// - GameEngine runs update/draw in requestAnimationFrame
// - Enemies follow path of tile nodes; towers auto-fire on nearest enemy in range

(function () {
  const canvas = document.getElementById('game-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  const tileSize = 32; // pixels per tile
  let level = null;

  // Simple helper to convert tile -> pixel center
  function tileToPx(t) {
    return t * tileSize + tileSize / 2;
  }

  // Distance helper
  function dist(ax, ay, bx, by) {
    const dx = ax - bx;
    const dy = ay - by;
    return Math.hypot(dx, dy);
  }

  // Visual style mapping for towers to allow easy differentiation later
  function visualsForTowerType(tCfg) {
    const name = (tCfg.name || '').toLowerCase();
    // Defaults with backend overrides
    let baseColor = tCfg.iconColor || '#60a5fa';
    let blinkColor = tCfg.iconBlinkColor || '#93c5fd';
    let beamColor = tCfg.beamColor || '#a7f3d0';
    let beamWidth = (typeof tCfg.beamWidth === 'number') ? tCfg.beamWidth : 2;
    let beamDash = [];
    let beamDuration = 0.12;
    if (tCfg.beamDash) {
      beamDash = String(tCfg.beamDash).split(',').map(s => parseFloat(s.trim())).filter(n => !isNaN(n) && n > 0);
    }

    if (name.includes('cannon')) {
      baseColor = tCfg.iconColor || baseColor || '#f59e0b';
      blinkColor = tCfg.iconBlinkColor || blinkColor || '#fbbf24';
      beamColor = tCfg.beamColor || beamColor || '#fcd34d';
      beamWidth = (typeof tCfg.beamWidth === 'number') ? tCfg.beamWidth : 3;
      if (!beamDash.length) beamDash = [6,6];
    } else if (name.includes('gatling')) {
      baseColor = tCfg.iconColor || baseColor || '#60a5fa';
      blinkColor = tCfg.iconBlinkColor || blinkColor || '#93c5fd';
      beamColor = tCfg.beamColor || beamColor || '#a7f3d0';
      beamWidth = (typeof tCfg.beamWidth === 'number') ? tCfg.beamWidth : 2;
    }

    return { baseColor, blinkColor, beamColor, beamWidth, beamDash, beamDuration };
  }

  // Visual style mapping for enemies by name; easy to extend later or move to backend
  function visualsForEnemyType(eType) {
    const name = (eType.name || '').toLowerCase();
    // Backend overrides first
    let baseColor = eType.iconColor || '#f87171';
    let hitColor = eType.iconHitColor || '#fca5a5';
    if (name.includes('runner')) {
      baseColor = eType.iconColor || baseColor || '#34d399';
      hitColor = eType.iconHitColor || hitColor || '#6ee7b7';
    } else if (name.includes('tank')) {
      baseColor = eType.iconColor || baseColor || '#a78bfa';
      hitColor = eType.iconHitColor || hitColor || '#c4b5fd';
    }
    return { baseColor, hitColor };
  }

  // Compute level specification from tower type + level number
  function computeLevelSpec(tCfg, levelNumber) {
    const growth = tCfg.growth || {};
    const damageGrowth = typeof growth.damage === 'number' ? growth.damage : (tCfg.growth_damage_mult || 1.0);
    const rangeGrowth = typeof growth.range === 'number' ? growth.range : (tCfg.growth_range_mult || 1.0);
    const fireGrowth = typeof growth.fireRate === 'number' ? growth.fireRate : (tCfg.growth_fire_rate_mult || 1.0);
    const costGrowth = typeof growth.cost === 'number' ? growth.cost : (tCfg.growth_cost_mult || 1.0);

    const result = {
      level: levelNumber,
      damageMult: Math.pow(Math.max(1.0, damageGrowth || 1.0), Math.max(0, levelNumber - 1)),
      rangeMult: Math.pow(Math.max(1.0, rangeGrowth || 1.0), Math.max(0, levelNumber - 1)),
      fireRateMult: Math.pow(Math.max(1.0, fireGrowth || 1.0), Math.max(0, levelNumber - 1)),
      costMult: Math.pow(Math.max(1.0, costGrowth || 1.0), Math.max(0, levelNumber - 1)),
      aoe: {
        additionalTargets: tCfg.aoeAdditionalTargets || 0,
        damageRatio: (typeof tCfg.aoeDamageRatio === 'number') ? tCfg.aoeDamageRatio : 0.75,
        range: tCfg.aoeRange || 0,
      },
      aoe2: { additionalTargets: 0, damageRatio: 0.25, range: 0 },
    };
    if (Array.isArray(tCfg.levels) && tCfg.levels.length) {
      const found = tCfg.levels.find(l => l.level === levelNumber) || tCfg.levels[0];
      if (found) {
        result.level = found.level;
        if (typeof found.damageMult === 'number') result.damageMult = found.damageMult;
        if (typeof found.rangeMult === 'number') result.rangeMult = found.rangeMult;
        if (typeof found.fireRateMult === 'number') result.fireRateMult = found.fireRateMult;
        if (typeof found.costMult === 'number') result.costMult = found.costMult;
        if (found.aoe) result.aoe = found.aoe;
        if (found.aoe2) result.aoe2 = found.aoe2;
      }
    }
    // Also compute absolute cost with stepwise rounding per level (ceil each step)
    const baseCost = tCfg.cost || 0;
    const g = Math.max(1.0, costGrowth || 1.0);
    let costAbs = Math.ceil(baseCost);
    for (let lvl = 2; lvl <= levelNumber; lvl++) {
      costAbs = Math.ceil(costAbs * g);
    }
    result.costAbs = costAbs;
    return result;
  }

  // Utility to format numbers for UI
  function fmt(n) { return (Math.round(n * 100) / 100).toString(); }

  // Shape helpers for towers and enemies
  function shapeForTowerType(tCfg) {
    if (tCfg.iconShape) return tCfg.iconShape;
    const name = (tCfg.name || '').toLowerCase();
    if (name.includes('cannon')) return 'triangle';
    if (name.includes('gatling')) return 'square';
    return 'square';
  }
  function shapeForEnemyType(eType) {
    if (eType.iconShape) return eType.iconShape;
    const name = (eType.name || '').toLowerCase();
    if (name.includes('runner')) return 'triangle';
    if (name.includes('tank')) return 'hex';
    return 'circle'; // grunt default
  }

  function drawPolygon(ctx, cx, cy, radius, sides, rotationRad, color) {
    ctx.fillStyle = color;
    ctx.beginPath();
    for (let i = 0; i < sides; i++) {
      const a = rotationRad + (i * 2 * Math.PI) / sides;
      const x = cx + Math.cos(a) * radius;
      const y = cy + Math.sin(a) * radius;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.fill();
  }
  function drawStar(ctx, cx, cy, outerR, innerR, points, rotationRad, color) {
    ctx.fillStyle = color;
    ctx.beginPath();
    const step = Math.PI / points;
    for (let i = 0; i < 2 * points; i++) {
      const r = (i % 2 === 0) ? outerR : innerR;
      const a = rotationRad + i * step;
      const x = cx + Math.cos(a) * r;
      const y = cy + Math.sin(a) * r;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.fill();
  }
  function drawShape(ctx, shape, cx, cy, size, color) {
    switch (shape) {
      case 'triangle':
        drawPolygon(ctx, cx, cy, size, 3, -Math.PI / 2, color);
        break;
      case 'hex':
        drawPolygon(ctx, cx, cy, size, 6, Math.PI / 6, color);
        break;
      case 'star':
        drawStar(ctx, cx, cy, size, size * 0.5, 5, -Math.PI / 2, color);
        break;
      case 'square':
        ctx.fillStyle = color;
        ctx.fillRect(cx - size, cy - size, size * 2, size * 2);
        break;
      default: // circle
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(cx, cy, size, 0, Math.PI * 2);
        ctx.fill();
    }
  }

  class Enemy {
    constructor(type, path, hpScale = 1.0) {
      this.type = type; // { id, name, hp, speed, bounty }
      this.hp = type.hp * hpScale;
      this.maxHp = this.hp; // store scaled max HP for bounty and UI
      this.path = path; // [{x,y}...]
      this.pathPosition = 0; // float: 0..(path.length-1)
      this.dead = false;
      this.escaped = false;
      this.hitFlash = 0; // seconds for quick hit highlight
      this.deathFade = 0; // seconds remaining for fade-out
      this.deathFadeTotal = 0.6; // total fade duration
      this.countedEscape = false; // ensure lives deducted once
      this.visuals = visualsForEnemyType(this.type);
    }

    get pos() {
      // Interpolate between path nodes
      const i = Math.floor(this.pathPosition);
      const frac = this.pathPosition - i;
      const a = this.path[Math.min(i, this.path.length - 1)];
      const b = this.path[Math.min(i + 1, this.path.length - 1)];
      const ax = tileToPx(a.x);
      const ay = tileToPx(a.y);
      const bx = tileToPx(b.x);
      const by = tileToPx(b.y);
      return { x: ax + (bx - ax) * frac, y: ay + (by - ay) * frac };
    }

    update(dt) {
      // Reduce visual timers
      if (this.hitFlash > 0) this.hitFlash = Math.max(0, this.hitFlash - dt);

      if (this.dead) {
        if (this.deathFade > 0) this.deathFade = Math.max(0, this.deathFade - dt);
        return; // stop moving when dead
      }

      // Move forward along path based on speed (tiles per second)
      const advance = this.type.speed * dt;
      this.pathPosition += advance;
      if (this.pathPosition >= this.path.length - 1) {
        this.escaped = true;
      }
    }
  }

  class Tower {
    constructor(cfg, x, y, levelNumber = 1) {
      this.cfg = cfg; // {id,name,cost,damage,range,fireRate}
      this.tileX = x;
      this.tileY = y;
      this.levelNumber = levelNumber;
      this.cooldown = 0; // seconds
      this.flash = 0; // seconds of fire flash
      this.visuals = visualsForTowerType(cfg);
      this.beamTimer = 0; // seconds remaining for beam visibility
      this.beamTarget = null; // {x,y} last shot target position
      this.shape = shapeForTowerType(cfg);
      this.levelSpec = computeLevelSpec(cfg, levelNumber);
    }
    get pos() {
      return { x: tileToPx(this.tileX), y: tileToPx(this.tileY) };
    }
    update(dt, enemies) {
      this.cooldown -= dt;
      if (this.flash > 0) this.flash = Math.max(0, this.flash - dt);
      if (this.beamTimer > 0) this.beamTimer = Math.max(0, this.beamTimer - dt);
      if (this.cooldown > 0) return null;
      // Find closest in range
      const me = this.pos;
      let best = null;
      let bestD = Infinity;
      for (const e of enemies) {
        if (e.dead || e.escaped) continue;
        const p = e.pos;
        const d = dist(me.x, me.y, p.x, p.y) / tileSize; // tiles
        const effRange = (this.cfg.range || 0) * (this.levelSpec.rangeMult || 1.0);
        if (d <= effRange && d < bestD) {
          best = e;
          bestD = d;
        }
      }
      if (best) {
        const targetPos = best.pos; // beam target frozen
        const hits = [];
        // Primary hit
        const primaryDamage = this.cfg.damage * (this.levelSpec.damageMult || 1.0);
        best.hp -= primaryDamage;
        best.hitFlash = 0.12;
        hits.push(best);

        // Additional AoE hits around primary within aoeRange (tiles)
        const { aoe, aoe2 } = this.levelSpec;
        const applyAoe = (ring, exclude) => {
          if (!ring) return [];
          const extraCount = ring.additionalTargets || 0;
          const extraRatio = (typeof ring.damageRatio === 'number') ? ring.damageRatio : 0.75;
          const aoeRange = ring.range || 0;
          const applied = [];
          if (extraCount > 0 && aoeRange > 0) {
            const candidates = [];
            for (const e of enemies) {
              if (exclude.has(e) || e.dead || e.escaped) continue;
              const p = e.pos;
              const dTiles = dist(targetPos.x, targetPos.y, p.x, p.y) / tileSize;
              if (dTiles <= aoeRange) {
                candidates.push({ e, d: dTiles });
              }
            }
            candidates.sort((a, b) => a.d - b.d);
            for (let i = 0; i < Math.min(extraCount, candidates.length); i++) {
              const ee = candidates[i].e;
              ee.hp -= primaryDamage * extraRatio;
              ee.hitFlash = 0.12;
              applied.push(ee);
              hits.push(ee);
            }
          }
          return applied;
        };
        const exclude = new Set([best]);
        const ring1 = applyAoe(aoe, exclude);
        ring1.forEach(e => exclude.add(e));
        const ring2 = applyAoe(aoe2, exclude);

        const effFireRate = Math.max(0.0001, (this.cfg.fireRate || 0) * (this.levelSpec.fireRateMult || 1.0));
        this.cooldown = 1 / effFireRate;
        this.flash = 0.12;
        this.beamTimer = this.visuals.beamDuration;
        this.beamTarget = { x: targetPos.x, y: targetPos.y };
        return hits; // array of enemies hit
      }
      return null;
    }
  }

  class GameEngine {
    constructor(levelConfig) {
      this.level = levelConfig;
      this.money = levelConfig.startMoney;
      this.lives = levelConfig.startLives;
      this.towers = [];
      this.enemies = [];
      this.currentWaveIndex = 0;
      this.timeSinceLastSpawn = 0;
      this.pendingSpawns = []; // [{type, remaining, interval, timer}]
      this.running = false;
      this.win = false;
      this.lose = false;

      // Tower building now requires selection from sidebar
      this.selectedTowerType = null;
      this.selectedTowerLevel = 1; // default level

      // Prepare first wave (but only spawn when Start Wave pressed)
      this._prepareWave();

      // Input: build on click
      canvas.addEventListener('click', (ev) => this._handleClick(ev));

      // UI
      document.getElementById('start-button').addEventListener('click', () => {
        if (!this.running && !this.win && !this.lose) {
          this.running = true; // start spawning/loop
        }
      });

      // Upgrade button
      const upBtn = document.getElementById('upgrade-btn');
      if (upBtn) {
        upBtn.addEventListener('click', () => this._upgradeSelected());
      }

      this.lastTs = performance.now();
      requestAnimationFrame((t) => this.loop(t));
      if (DEBUG_ENABLED && this.updateDebug) this.updateDebug('init');
    }

    _handleClick(ev) {
      const rect = canvas.getBoundingClientRect();
      const x = ev.clientX - rect.left;
      const y = ev.clientY - rect.top;
      const tx = Math.floor(x / tileSize);
      const ty = Math.floor(y / tileSize);
      // If clicking an existing tower, select it
      const existing = this.towers.find(t => t.tileX === tx && t.tileY === ty);
      if (existing) {
        this.selectedPlacedTower = existing;
        this._updateSelectedPanel();
        return;
      }
      // If click on build spot and enough money, place selected tower
      const onSpot = this.level.buildSpots.some((s) => s.x === tx && s.y === ty);
      const occupied = this.towers.some((t) => t.tileX === tx && t.tileY === ty);
      if (onSpot && !occupied && this.selectedTowerType) {
        // Determine cost for selected level
        const lvlSpec = computeLevelSpec(this.selectedTowerType, this.selectedTowerLevel);
        const cost = lvlSpec.costAbs || Math.round(this.selectedTowerType.cost * (lvlSpec.costMult || 1.0));
        if (this.money >= cost) {
          const t = new Tower(this.selectedTowerType, tx, ty, this.selectedTowerLevel);
          this.towers.push(t);
          this.money -= cost;
          this.selectedPlacedTower = t;
          this._updateSelectedPanel();
        }
      }
    }

    _upgradeSelected() {
      const t = this.selectedPlacedTower;
      if (!t) return;
      if (t.levelNumber >= 100) return;
      const nextLevel = t.levelNumber + 1;
      const specNext = computeLevelSpec(t.cfg, nextLevel);
      const cost = specNext.costAbs || Math.ceil((t.cfg.cost || 0) * (specNext.costMult || 1.0));
      if (this.money < cost) return;
      this.money -= cost;
      t.levelNumber = nextLevel;
      t.levelSpec = computeLevelSpec(t.cfg, t.levelNumber);
      this._updateSelectedPanel();
    }

    _updateSelectedPanel() {
      const el = document.getElementById('sel-info');
      const upBtn = document.getElementById('upgrade-btn');
      if (!el) return;
      const t = this.selectedPlacedTower;
      if (!t) {
        el.textContent = 'None';
        if (upBtn) upBtn.disabled = true;
        return;
      }
      const dmg = (t.cfg.damage || 0) * (t.levelSpec.damageMult || 1.0);
      const rng = (t.cfg.range || 0) * (t.levelSpec.rangeMult || 1.0);
      const fr = (t.cfg.fireRate || 0) * (t.levelSpec.fireRateMult || 1.0);
      el.textContent = `${t.cfg.name} Lv ${t.levelNumber}\nDamage: ${fmt(dmg)}  Range: ${fmt(rng)}  Fire: ${fmt(fr)}`;
      if (upBtn) {
        if (t.levelNumber >= 100) {
          upBtn.textContent = 'Max Level';
          upBtn.disabled = true;
        } else {
          const specNext = computeLevelSpec(t.cfg, t.levelNumber + 1);
          const cost = specNext.costAbs || Math.ceil((t.cfg.cost || 0) * (specNext.costMult || 1.0));
          upBtn.textContent = `Upgrade to Lv ${t.levelNumber + 1} ($${cost})`;
          upBtn.disabled = this.money < cost;
        }
      }
    }

  _prepareWave() {
    if (this.currentWaveIndex >= this.level.waves.length) return;
    const w = this.level.waves[this.currentWaveIndex];
    const groups = w.groups || w.enemies || [];
    this.pendingSpawns = groups.map((g) => ({
      type: this.level.enemyTypes.find((et) => et.id === g.typeId),
      remaining: g.count,
      interval: g.spawnInterval,
      timer: 0,
      delay: g.startDelay || 0,
    }));
    if (DEBUG_ENABLED && this.updateDebug) this.updateDebug('prepare-wave');
  }

    _spawnLogic(dt) {
      if (this.currentWaveIndex >= this.level.waves.length) return; // no more waves
      for (const sp of this.pendingSpawns) {
        if (sp.delay > 0) { sp.delay -= dt; continue; }
        sp.timer -= dt;
        if (sp.remaining > 0 && sp.timer <= 0) {
          const hpScale = Math.pow(1.02, Math.max(0, this.currentWaveIndex));
          this.enemies.push(new Enemy(sp.type, this.level.path, hpScale));
          sp.remaining -= 1;
          sp.timer = sp.interval;
        }
      }
      // If all spawned and no enemies alive/escaping, move to next wave
      const allSpawned = this.pendingSpawns.every((sp) => sp.remaining <= 0);
      const anyAlive = this.enemies.some((e) => !e.dead && !e.escaped);
      if (allSpawned && !anyAlive) {
        this.currentWaveIndex += 1;
        if (this.currentWaveIndex >= this.level.waves.length) {
          if (this.level.infinite) {
            // Generate next wave and continue
            const nextNum = this.currentWaveIndex + 1; // waves are 1-based in display
            const next = generateInfiniteWave(nextNum, this.level.enemyTypes);
            this.level.waves.push(next);
            this._prepareWave();
            this.running = true; // auto-continue in infinite mode
          } else {
            // Stage complete in single-level mode; in campaign mode, CampaignEngine will handle next stage.
            this.win = true;
            this.running = false;
            if (this.onStageComplete) this.onStageComplete();
          }
        } else {
          this._prepareWave();
          this.running = false; // wait for start button again to begin next wave
        }
      }
    }

    update(dt) {
      if (this.running && !this.win && !this.lose) {
        this._spawnLogic(dt);
      }

      // Enemies
      for (const e of this.enemies) {
        e.update(dt);
        if (!e.dead && e.escaped && !e.countedEscape) {
          e.countedEscape = true;
          this.lives -= 1;
          if (this.lives <= 0) {
            this.lose = true;
            this.running = false;
          }
        }
      }

      // Towers fire (support multi-hit)
      let bountyAwarded = false;
      for (const t of this.towers) {
        const hits = t.update(dt, this.enemies);
        if (hits && hits.length) {
          for (const h of hits) {
            if (h.hp <= 0 && !h.dead) {
              h.dead = true;
              h.deathFade = h.deathFadeTotal; // start fade-out
              this.money += computeBounty(h);
              bountyAwarded = true;
            }
          }
        }
      }
      if (bountyAwarded) this._updateSelectedPanel();

      // Clean up: keep dead enemies until fade completes
      this.enemies = this.enemies.filter((e) => !e.escaped && !(e.dead && e.deathFade <= 0));

      // Update UI
      document.getElementById('money').textContent = Math.floor(this.money);
      document.getElementById('lives').textContent = this.lives;
      document.getElementById('wave').textContent = Math.min(this.currentWaveIndex + 1, this.level.waves.length);

      const msg = document.getElementById('td-message');
      if (this.lose) {
        msg.hidden = false;
        msg.textContent = 'Game Over';
      } else if (this.win) {
        msg.hidden = false;
        msg.textContent = 'You Win!';
      } else {
        msg.hidden = true;
      }
    }

    drawGrid() {
      const cols = this.level.width;
      const rows = this.level.height;
      ctx.strokeStyle = '#1f2937';
      ctx.lineWidth = 1;
      for (let x = 0; x <= cols; x++) {
        ctx.beginPath();
        ctx.moveTo(x * tileSize, 0);
        ctx.lineTo(x * tileSize, rows * tileSize);
        ctx.stroke();
      }
      for (let y = 0; y <= rows; y++) {
        ctx.beginPath();
        ctx.moveTo(0, y * tileSize);
        ctx.lineTo(cols * tileSize, y * tileSize);
        ctx.stroke();
      }
    }

    draw() {
      // Clear
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Path as filled tiles
      ctx.fillStyle = '#374151';
      for (let i = 0; i < this.level.path.length; i++) {
        const n = this.level.path[i];
        ctx.fillRect(n.x * tileSize, n.y * tileSize, tileSize, tileSize);
      }

      // Build spots
      ctx.fillStyle = '#10b981';
      for (const s of this.level.buildSpots) {
        ctx.fillRect(
          s.x * tileSize + tileSize * 0.25,
          s.y * tileSize + tileSize * 0.25,
          tileSize * 0.5,
          tileSize * 0.5
        );
      }

      // Tower ranges (tile overlay)
      this.drawTowerRanges();

      // Towers
      for (const t of this.towers) {
        const color = t.flash > 0 ? t.visuals.blinkColor : t.visuals.baseColor;
        const px = t.tileX * tileSize + tileSize * 0.5;
        const py = t.tileY * tileSize + tileSize * 0.5;
        drawShape(ctx, t.shape, px, py, tileSize * 0.35, color);
        // Level badge
        ctx.save();
        ctx.fillStyle = '#0b1220';
        ctx.strokeStyle = '#1f2937';
        ctx.lineWidth = 1;
        const badgeW = 16, badgeH = 12;
        const bx = px - badgeW/2, by = py - tileSize*0.5 + 2;
        ctx.fillRect(bx, by, badgeW, badgeH);
        ctx.strokeRect(bx, by, badgeW, badgeH);
        ctx.fillStyle = '#e5e7eb';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(String(t.levelNumber), bx + badgeW/2, by + badgeH/2 + 0.5);
        ctx.restore();
      }

      // Enemies
      for (const e of this.enemies) {
        const p = e.pos;
        // Compute color and alpha based on state
        let base = e.visuals.baseColor;
        if (e.hitFlash > 0 && !e.dead) base = e.visuals.hitColor || e.visuals.baseColor;
        const shape = shapeForEnemyType(e.type);

        // Set alpha for death fade
        if (e.dead) {
          const alpha = Math.max(0, e.deathFade / e.deathFadeTotal);
          ctx.save();
          ctx.globalAlpha = alpha;
          drawShape(ctx, shape, p.x, p.y, tileSize * 0.3, base);
          ctx.restore();
        } else {
          drawShape(ctx, shape, p.x, p.y, tileSize * 0.3, base);
        }
  }

  // Beams (draw on top)
  for (const t of this.towers) {
        if (t.beamTimer > 0 && t.beamTarget) {
          const me = t.pos;
          const alpha = Math.max(0, t.beamTimer / t.visuals.beamDuration);
          ctx.save();
          ctx.strokeStyle = t.visuals.beamColor;
          ctx.lineWidth = t.visuals.beamWidth;
          if (t.visuals.beamDash && t.visuals.beamDash.length) {
            ctx.setLineDash(t.visuals.beamDash);
          } else {
            ctx.setLineDash([]);
          }
          ctx.globalAlpha = alpha;
          ctx.beginPath();
          ctx.moveTo(me.x, me.y);
          ctx.lineTo(t.beamTarget.x, t.beamTarget.y);
          ctx.stroke();
          ctx.restore();
        }
      }

      this.drawGrid();
    }

    updateDebug(tag) {
      try {
        let box = document.getElementById('debug-box');
        if (!box) {
          // Create on the fly so old templates still work
          const host = document.getElementById('stage-overlay') || canvas.parentElement || document.body;
          box = document.createElement('div');
          box.id = 'debug-box';
          box.style.cssText = 'margin-top:.5rem;background:#0b1220;color:#e5e7eb;border:1px solid #374151;border-radius:.25rem;padding:.5rem;font-size:12px;white-space:pre-line;';
          host.appendChild(box);
        }
        box.style.display = DEBUG_ENABLED ? 'block' : 'none';
        if (!DEBUG_ENABLED) return;
        const lvl = this.level || {};
        const waves = Array.isArray(lvl.waves) ? lvl.waves : [];
        const current = waves[this.currentWaveIndex] || {};
        const groupsCount = (current.groups || current.enemies || []).length || 0;
        const text = [
          `Mode: ${lvl.infinite ? 'Single Map (Infinite)' : 'Campaign/Single'}`,
          `Map: ${lvl.name || '(unnamed)'} (#${lvl.id || '?'}) ${lvl.width || '?'}x${lvl.height || '?'}`,
          `Path nodes: ${lvl.path ? lvl.path.length : 0}  Build spots: ${lvl.buildSpots ? lvl.buildSpots.length : 0}`,
          `Towers: ${lvl.towerTypes ? lvl.towerTypes.length : 0}  Enemies: ${lvl.enemyTypes ? lvl.enemyTypes.length : 0}`,
          `Waves: ${waves.length}  Current: ${Math.min(this.currentWaveIndex + 1, Math.max(1, waves.length))}  Groups in current: ${groupsCount}`,
          `Money: ${Math.floor(this.money)}  Lives: ${this.lives}  Tag: ${tag}`,
        ].join('\n');
        box.textContent = text;
      } catch (e) {}
    }

    // Draw tile overlays for each tower range
    drawTowerRanges() {
      ctx.save();
      for (const t of this.towers) {
        const range = (t.cfg.range || 0) * (t.levelSpec.rangeMult || 1.0); // tiles
        ctx.globalAlpha = 0.12;
        ctx.fillStyle = t.visuals.baseColor;
        const minX = Math.max(0, Math.floor(t.tileX - range));
        const maxX = Math.min(this.level.width - 1, Math.ceil(t.tileX + range));
        const minY = Math.max(0, Math.floor(t.tileY - range));
        const maxY = Math.min(this.level.height - 1, Math.ceil(t.tileY + range));
        for (let ty = minY; ty <= maxY; ty++) {
          for (let tx = minX; tx <= maxX; tx++) {
            const d = Math.hypot((tx + 0.5) - (t.tileX + 0.5), (ty + 0.5) - (t.tileY + 0.5));
            if (d <= range) {
              ctx.fillRect(tx * tileSize, ty * tileSize, tileSize, tileSize);
            }
          }
        }
      }
      ctx.restore();
    }

    loop(ts) {
      const dt = Math.min(0.05, (ts - this.lastTs) / 1000); // clamp dt
      this.lastTs = ts;
      this.update(dt);
      this.draw();
      requestAnimationFrame((t) => this.loop(t));
    }
  }

  function getQueryInt(name, defVal){
    const u = new URL(window.location.href);
    const v = parseInt(u.searchParams.get(name)||'',10);
    return Number.isFinite(v) && v>0 ? v : defVal;
  }
function getQueryFlag(name){
  const u = new URL(window.location.href);
  const v = u.searchParams.get(name);
  return v === '1' || v === 'true';
}
const DEBUG_ENABLED = getQueryFlag('debug');

  async function init() {
    const campaignId = getQueryInt('campaign', 0);
    if (campaignId > 0) {
      // Campaign mode: fetch campaign and start on stage 0
      let campaign;
      try {
        const res = await fetch(`/td-now/api/campaigns/${campaignId}/`);
        if (!res.ok) throw new Error('HTTP '+res.status);
        campaign = await res.json();
      } catch (err) {
        const msg = document.getElementById('td-message');
        if (msg) { msg.hidden = false; msg.textContent = `Failed to load campaign ${campaignId}: ${err}`; }
        return;
      }
      // Prepare stages by embedding map config into level-like entries
      const stages = campaign.stages.map(st => ({
        id: st.map.id,
        name: st.map.name,
        width: st.map.width,
        height: st.map.height,
        path: st.map.path,
        buildSpots: st.map.buildSpots,
        startMoney: campaign.startMoney, // used only on first stage
        startLives: campaign.startLives,
        towerTypes: campaign.towerTypes,
        enemyTypes: campaign.enemyTypes,
        waves: ensureWaves(st.waves, campaign.enemyTypes),
        message: st.message || '',
        startMoneyOverride: st.startMoneyOverride,
        startLivesOverride: st.startLivesOverride,
      }));

      // Campaign-aware engine wrapper
      const engine = new CampaignEngine(stages, campaign.towerTypes || []);
      return;
    }

    // Single-level mode: Resize canvas based on level size after fetch
    const mapId = getQueryInt('map', 1);
    const res = await fetch(`/td-now/api/levels/${mapId}/`);
    level = await res.json();

    canvas.width = level.width * tileSize;
    canvas.height = level.height * tileSize;

    // Start engine
    const infinite = getQueryFlag('infinite');
    if (infinite) {
      level.infinite = true;
      // Ensure at least first wave for infinite mode
      level.waves = [ generateInfiniteWave(1, level.enemyTypes) ];
    } else {
      level.waves = ensureWaves(level.waves, level.enemyTypes);
    }
    const engine = new GameEngine(level);
    validateLevelForPlay(level, engine);
    buildSidebar(engine, level.towerTypes);
    return;
  }

  function buildSidebar(engine, towerTypes) {
    const list = document.getElementById('tower-list');
    if (!list) return;
    list.innerHTML = '';
    // Fallback: use engine.level.towerTypes if not provided
    const ttypes = (towerTypes && towerTypes.length) ? towerTypes : (engine && engine.level ? engine.level.towerTypes : []);
    const items = [];
    ttypes.forEach((t) => {
      const unlocked = (typeof t.unlocked === 'undefined') ? true : !!t.unlocked;
      const li = document.createElement('div');
      li.className = 'td-tower-item' + (unlocked ? '' : ' locked');
      li.dataset.towerId = String(t.id);

      const mini = document.createElement('canvas');
      mini.width = 40; mini.height = 40; mini.className = 'td-mini';
      li.appendChild(mini);

      const name = document.createElement('div');
      name.className = 'td-tw-name';
      name.textContent = `${t.name} (Lv1)`;
      li.appendChild(name);

      const cost = document.createElement('div');
      cost.className = 'td-tw-cost';
      cost.textContent = `$${t.cost}`;
      li.appendChild(cost);

      if (unlocked) {
        li.addEventListener('click', () => {
          items.forEach((el) => el.classList.remove('selected'));
          li.classList.add('selected');
          engine.selectedTowerType = t;
          engine.selectedTowerLevel = 1; // default for now
        });
      }

      list.appendChild(li);
      items.push(li);

      // Draw mini shape
      const mctx = mini.getContext('2d');
      const visuals = visualsForTowerType(t);
      const shape = shapeForTowerType(t);
      drawShape(mctx, shape, 20, 20, 12, visuals.baseColor);
    });
  }
  // Generate wave definition for infinite mode
  function generateInfiniteWave(waveNum, enemyTypes) {
    const findByName = (name) => enemyTypes.find(e => (e.name||'').toLowerCase() === name);
    const grunt = findByName('grunt') || enemyTypes[0];
    const runner = findByName('runner') || enemyTypes[1] || enemyTypes[0];
    const tank = findByName('tank') || enemyTypes[2] || enemyTypes[0];
    const boss = findByName('boss') || enemyTypes.slice().sort((a,b)=> (b.hp||0)-(a.hp||0))[0];
    const groups = [];
    const n = waveNum % 10;
    const set = Math.floor((waveNum-1)/10); // 0-based set count
    const add = (type, count, interval, delay=0)=> groups.push({ typeId: type.id, count, spawnInterval: interval, startDelay: delay });
    if (n === 0) {
      // Boss wave
      const bosses = Math.max(1, Math.floor(waveNum/10));
      add(boss, bosses, 2.0, 0);
    } else {
      switch(n) {
        case 1: add(grunt, 10, 0.8, 0); break;
        case 2: add(grunt, 10, 0.8, 0); add(runner, 10, 1.0, 5); break;
        case 3: add(runner, 12, 0.9, 0); break;
        case 4: add(grunt, 10, 0.8, 0); add(tank, 8, 1.5, 5); break;
        case 5: add(grunt, 10, 0.8, 0); add(runner, 10, 1.0, 2); add(tank, 4, 1.8, 6); break;
        case 6: add(runner, 14, 0.8, 0); break;
        case 7: add(tank, 6, 2.0, 0); break;
        case 8: add(grunt, 12, 0.8, 0); add(runner, 12, 1.0, 0); break;
        case 9: add(grunt, 16, 0.7, 0); add(runner, 8, 0.9, 3); break;
      }
    }
    return { number: waveNum, groups };
  }

  // Ensure waves exist; if missing, generate a simple default set using available enemy types
  function ensureWaves(waves, enemyTypes) {
    if (Array.isArray(waves) && waves.length) return waves;
    const e = enemyTypes || [];
    if (!e.length) return [];
    const first = e[0]?.id, second = e[1]?.id, third = e[2]?.id;
    const out = [];
    // Wave 1: 10 of first
    out.push({ number: 1, groups: [{ typeId: first, count: 10, spawnInterval: 0.8, startDelay: 0 }] });
    // Wave 2: 10 first then 10 second (if exists)
    out.push({ number: 2, groups: [
      { typeId: first, count: 10, spawnInterval: 0.8, startDelay: 0 },
      { typeId: (second || first), count: 10, spawnInterval: 1.0, startDelay: 5 },
    ]});
    // Wave 3: 10 second then 8 third (fallback to first/second)
    out.push({ number: 3, groups: [
      { typeId: (second || first), count: 10, spawnInterval: 1.0, startDelay: 0 },
      { typeId: (third || (second || first)), count: 8, spawnInterval: 1.5, startDelay: 5 },
    ]});
    return out;
  }

  function validateLevelForPlay(level, engine) {
    const btn = document.getElementById('start-button');
    const msg = document.getElementById('td-message');
    if (!Array.isArray(level.path) || level.path.length < 2) {
      if (btn) btn.disabled = true;
      if (msg) { msg.hidden = false; msg.textContent = 'Map has no valid path. Open Map Builder to add a path (at least 2 nodes).'; }
    }
  }

  // Compute bounty with wave scaling: default = scaled health / 4 (rounded),
  // but never less than the static bounty configured on the enemy type.
  function computeBounty(enemy) {
    const dyn = Math.round((enemy.maxHp || enemy.type.hp || 0) / 4);
    const stat = (typeof enemy.type.bounty === 'number') ? enemy.type.bounty : 0;
    return Math.max(stat, dyn);
  }

  init().catch((e) => console.error('Failed to init TD Now:', e));
})();
  class CampaignEngine {
    constructor(stages, allTowers=[]) {
      this.stages = stages;
      this.index = 0;
      this.money = stages[0].startMoney;
      this.lives = stages[0].startLives;
      this.engine = null;
      this.allTowers = allTowers;
      this._startStage(0);
    }

    _startStage(i) {
      this.index = i;
      const levelConfig = Object.assign({}, this.stages[i]);
      // Determine starting resources with overrides, falling back to carry-over or campaign defaults
      const st = this.stages[i];
      const baseMoney = (i === 0) ? (st.startMoneyOverride != null ? st.startMoneyOverride : st.startMoney) : this.money;
      const baseLives = (i === 0) ? (st.startLivesOverride != null ? st.startLivesOverride : st.startLives) : this.lives;
      levelConfig.startMoney = (st.startMoneyOverride != null) ? st.startMoneyOverride : baseMoney;
      levelConfig.startLives = (st.startLivesOverride != null) ? st.startLivesOverride : baseLives;
      // Ensure minimal config exists
      if (!Array.isArray(levelConfig.waves) || !levelConfig.waves.length) {
        levelConfig.waves = ensureWaves([], levelConfig.enemyTypes || []);
      }
      if (!Array.isArray(levelConfig.towerTypes) || !levelConfig.towerTypes.length) {
        // fallback to previous stage's towers if available
        if (this.index > 0) levelConfig.towerTypes = this.stages[this.index-1].towerTypes;
      }

      canvas.width = levelConfig.width * tileSize;
      canvas.height = levelConfig.height * tileSize;
      this.engine = new GameEngine(levelConfig);
      // Carry over start values
      this.engine.money = levelConfig.startMoney;
      this.engine.lives = levelConfig.startLives;
      this.engine.onStageComplete = () => this._showStageMessage();
      validateLevelForPlay(levelConfig, this.engine);
      // Show current stats immediately
      this.engine._updateSelectedPanel && this.engine._updateSelectedPanel();
      // Ensure sidebar reflects current towers
      const towersForStage = (levelConfig.towerTypes && levelConfig.towerTypes.length) ? levelConfig.towerTypes : (this.allTowers || []);
      if (!levelConfig.towerTypes || !levelConfig.towerTypes.length) {
        this.engine.level.towerTypes = towersForStage;
      }
      buildSidebar(this.engine, towersForStage);
      if (DEBUG_ENABLED && this.engine.updateDebug) this.engine.updateDebug('stage-start');
    }

    _showStageMessage() {
      const msgBox = document.getElementById('stage-msg');
      const msgText = document.getElementById('stage-msg-text');
      const btn = document.getElementById('stage-continue');
      if (!msgBox || !btn || !msgText) return this._nextStage();
      const st = this.stages[this.index];
      msgText.textContent = st.message || 'Stage Complete';
      msgBox.style.display = 'block';
      const onClick = () => {
        msgBox.style.display = 'none';
        btn.removeEventListener('click', onClick);
        this._nextStage();
      };
      btn.addEventListener('click', onClick);
    }

    _nextStage() {
      // Stage done; carry over state
      this.money = this.engine.money;
      this.lives = this.engine.lives;
      if (this.index + 1 < this.stages.length) {
        this._startStage(this.index + 1);
        // Rebuild sidebar for possibly different tower list
        buildSidebar(this.getCurrentEngine(), this.stages[this.index].towerTypes);
      } else {
        // Campaign complete: show message
        const msg = document.getElementById('td-message');
        if (msg) {
          msg.hidden = false;
          msg.textContent = 'Campaign Complete!';
        }
      }
    }

    getCurrentEngine() { return this.engine; }
  }
