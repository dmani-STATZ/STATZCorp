// Simple Tower & Enemy editor (CRUD lite)
(function(){
  const towersEl = document.getElementById('towers');
  const enemiesEl = document.getElementById('enemies');
  if (!towersEl || !enemiesEl) return;

  function getCSRF(){ const m = document.cookie.match(/csrftoken=([^;]+)/); return m? m[1]:''; }

  const SHAPES = ['square','triangle','hex','star','circle'];

  function drawShape(ctx, shape, cx, cy, size, color){
    ctx.clearRect(0,0,ctx.canvas.width,ctx.canvas.height);
    ctx.fillStyle = color;
    switch(shape){
      case 'triangle':
        polygon(3, -Math.PI/2); break;
      case 'hex':
        polygon(6, Math.PI/6); break;
      case 'star':
        star(); break;
      case 'square':
        ctx.fillRect(cx-size, cy-size, size*2, size*2); break;
      default:
        ctx.beginPath(); ctx.arc(cx,cy,size,0,Math.PI*2); ctx.fill(); break;
    }
    function polygon(sides, rot){
      ctx.beginPath();
      for(let i=0;i<sides;i++){
        const a = rot + i*2*Math.PI/sides;
        const x = cx + Math.cos(a)*size; const y = cy + Math.sin(a)*size;
        if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
      }
      ctx.closePath(); ctx.fill();
    }
    function star(){
      ctx.beginPath(); const pts=5, step=Math.PI/pts;
      for(let i=0;i<pts*2;i++){
        const r = (i%2===0)? size : size*0.5;
        const a = -Math.PI/2 + i*step;
        const x = cx + Math.cos(a)*r; const y = cy + Math.sin(a)*r;
        if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
      }
      ctx.closePath(); ctx.fill();
    }
  }

  function makeInput(label, type, value){
    const wrap = document.createElement('div');
    const l = document.createElement('label'); l.textContent = label;
    const i = document.createElement('input'); i.type = type; i.value = value ?? '';
    wrap.append(l, i); return [wrap,i];
  }
  function makeSelect(label, value){
    const wrap = document.createElement('div');
    const l = document.createElement('label'); l.textContent = label;
    const s = document.createElement('select'); SHAPES.forEach(sh=>{ const o=document.createElement('option'); o.value=sh;o.textContent=sh; s.appendChild(o); }); s.value=value||'square';
    wrap.append(l,s); return [wrap,s];
  }
  function makeColor(label, value){ return makeInput(label, 'color', value||'#60a5fa'); }

  async function loadAll(){
    const [tRes,eRes] = await Promise.all([
      fetch('/td-now/api/towers/'),
      fetch('/td-now/api/enemies/'),
    ]);
    const towers = await tRes.json(); const enemies = await eRes.json();
    renderTowers(towers); renderEnemies(enemies);
  }

  function renderTowers(items){
    towersEl.innerHTML = '';
    items.forEach(t => towersEl.appendChild(towerRow(t)));
  }
  function renderEnemies(items){
    enemiesEl.innerHTML = '';
    items.forEach(e => enemiesEl.appendChild(enemyRow(e)));
  }

  function towerRow(t){
    const row = document.createElement('div'); row.className='row';
    const grid = document.createElement('div'); grid.className='grid'; row.appendChild(grid);
    const [nWrap,n] = makeInput('Name', 'text', t.name); grid.appendChild(nWrap);
    const [costWrap,cost] = makeInput('Cost', 'number', t.cost); grid.appendChild(costWrap);
    const [dWrap,dmg] = makeInput('Damage', 'number', t.damage); grid.appendChild(dWrap);
    const [rWrap,rng] = makeInput('Range', 'number', t.range); grid.appendChild(rWrap);
    const [frWrap,fr] = makeInput('Fire Rate', 'number', t.fireRate); grid.appendChild(frWrap);
    const [shapeWrap,shape] = makeSelect('Icon Shape', t.iconShape); grid.appendChild(shapeWrap);
    const [colorWrap,color] = makeColor('Icon Color', t.iconColor); grid.appendChild(colorWrap);
    const [blinkWrap,blink] = makeColor('Blink Color', t.iconBlinkColor || '#93c5fd'); grid.appendChild(blinkWrap);
    const [beamWrap,beam] = makeColor('Beam Color', t.beamColor || '#a7f3d0'); grid.appendChild(beamWrap);
    const [bwWrap,bw] = makeInput('Beam Width', 'number', t.beamWidth || 2); grid.appendChild(bwWrap);
    const [bdWrap,bd] = makeInput('Beam Dash', 'text', t.beamDash || ''); grid.appendChild(bdWrap);

    const preview = document.createElement('canvas'); preview.width=64; preview.height=64; preview.className='mini'; row.appendChild(preview);
    const pctx = preview.getContext('2d');
    function updatePreview(){ drawShape(pctx, shape.value, 32, 32, 18, color.value); }
    [shape,color].forEach(el=> el.addEventListener('input', updatePreview)); updatePreview();

    const actions = document.createElement('div'); actions.className='actions'; row.appendChild(actions);
    const save = document.createElement('button'); save.className='btn'; save.textContent='Save';
    save.addEventListener('click', async ()=>{
      const payload = {
        name: n.value, cost: parseInt(cost.value,10)||0, damage: parseFloat(dmg.value)||0,
        range: parseFloat(rng.value)||0, fireRate: parseFloat(fr.value)||0,
        iconShape: shape.value, iconColor: color.value, iconBlinkColor: blink.value,
        beamColor: beam.value, beamWidth: parseInt(bw.value,10)||2, beamDash: bd.value,
      };
      const url = t.id ? `/td-now/api/towers/${t.id}/` : '/td-now/api/towers/create/';
      const method = t.id ? 'PUT' : 'POST';
      const res = await fetch(url, { method, headers: { 'Content-Type':'application/json', 'X-CSRFToken': getCSRF() }, body: JSON.stringify(payload) });
      if (!res.ok) return alert('Save failed: '+await res.text());
      loadAll();
    });
    actions.appendChild(save);
    return row;
  }

  function enemyRow(e){
    const row = document.createElement('div'); row.className='row';
    const grid = document.createElement('div'); grid.className='grid'; row.appendChild(grid);
    const [nWrap,n] = makeInput('Name','text', e.name); grid.appendChild(nWrap);
    const [hpWrap,hp] = makeInput('HP','number', e.hp || e.max_health || 30); grid.appendChild(hpWrap);
    const [spWrap,sp] = makeInput('Speed','number', e.speed || 1); grid.appendChild(spWrap);
    const [boWrap,bo] = makeInput('Base Bounty','number', e.bounty || 5); grid.appendChild(boWrap);
    const [shapeWrap,shape] = makeSelect('Icon Shape', e.iconShape || 'circle'); grid.appendChild(shapeWrap);
    const [colorWrap,color] = makeColor('Icon Color', e.iconColor || '#f87171'); grid.appendChild(colorWrap);
    const [hitWrap,hit] = makeColor('Hit Color', e.iconHitColor || '#fca5a5'); grid.appendChild(hitWrap);

    const preview = document.createElement('canvas'); preview.width=64; preview.height=64; preview.className='mini'; row.appendChild(preview);
    const pctx = preview.getContext('2d');
    function updatePreview(){ drawShape(pctx, shape.value, 32, 32, 18, color.value); }
    [shape,color].forEach(el=> el.addEventListener('input', updatePreview)); updatePreview();

    const actions = document.createElement('div'); actions.className='actions'; row.appendChild(actions);
    const save = document.createElement('button'); save.className='btn'; save.textContent='Save';
    save.addEventListener('click', async ()=>{
      const payload = {
        name: n.value, hp: parseFloat(hp.value)||0, speed: parseFloat(sp.value)||0, bounty: parseInt(bo.value,10)||0,
        iconShape: shape.value, iconColor: color.value, iconHitColor: hit.value,
      };
      const url = e.id ? `/td-now/api/enemies/${e.id}/` : '/td-now/api/enemies/create/';
      const method = e.id ? 'PUT' : 'POST';
      const res = await fetch(url, { method, headers: { 'Content-Type':'application/json', 'X-CSRFToken': getCSRF() }, body: JSON.stringify(payload) });
      if (!res.ok) return alert('Save failed: '+await res.text());
      loadAll();
    });
    actions.appendChild(save);
    return row;
  }

  document.getElementById('add-tower').addEventListener('click', ()=> towersEl.prepend(towerRow({})););
  document.getElementById('add-enemy').addEventListener('click', ()=> enemiesEl.prepend(enemyRow({})););

  loadAll();
})();
