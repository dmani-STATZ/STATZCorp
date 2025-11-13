// Simple Map Builder for TD Now
// - Click to add Path tiles in order (click order is saved as path order)
// - Click to toggle Build spots
// - Erase tool removes either
// - Save posts to /td-now/api/maps/

(function(){
  const canvas = document.getElementById('builder-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  const nameEl = document.getElementById('map-name');
  const widthEl = document.getElementById('map-width');
  const heightEl = document.getElementById('map-height');
  const statPath = document.getElementById('stat-path');
  const statBuild = document.getElementById('stat-build');
  const loadSel = document.getElementById('builder-load');
  const loadBtn = document.getElementById('builder-load-btn');
  const resetBtn = document.getElementById('builder-reset-btn');

  const tileSize = 32; // px
  let widthTiles = parseInt(widthEl.value, 10) || 30;
  let heightTiles = parseInt(heightEl.value, 10) || 20;
  let tool = 'path'; // 'path' | 'build' | 'erase'
  let isDragging = false;
  let loadedMapId = null;

  // Data
  const path = []; // ordered array of {x,y}
  const buildSpots = new Set(); // store as 'x,y'

  function key(x,y){ return x+','+y; }
  function fromKey(k){ const [x,y] = k.split(',').map(Number); return {x,y}; }

  function resizeCanvas(){
    canvas.width = widthTiles * tileSize;
    canvas.height = heightTiles * tileSize;
    draw();
  }

  function setTool(next){
    tool = next;
    document.querySelectorAll('.builder-tools .tool').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tool === tool);
    });
  }

  function drawGrid(){
    ctx.strokeStyle = '#1f2937';
    ctx.lineWidth = 1;
    for (let x = 0; x <= widthTiles; x++){
      ctx.beginPath();
      ctx.moveTo(x*tileSize, 0);
      ctx.lineTo(x*tileSize, heightTiles*tileSize);
      ctx.stroke();
    }
    for (let y = 0; y <= heightTiles; y++){
      ctx.beginPath();
      ctx.moveTo(0, y*tileSize);
      ctx.lineTo(widthTiles*tileSize, y*tileSize);
      ctx.stroke();
    }
  }

  function draw(){
    ctx.clearRect(0,0,canvas.width,canvas.height);
    // Path tiles
    ctx.fillStyle = '#374151';
    for (const n of path){
      ctx.fillRect(n.x*tileSize, n.y*tileSize, tileSize, tileSize);
    }
    // Build spots
    ctx.fillStyle = '#10b981';
    for (const k of buildSpots){
      const n = fromKey(k);
      ctx.fillRect(n.x*tileSize + tileSize*0.25, n.y*tileSize + tileSize*0.25, tileSize*0.5, tileSize*0.5);
    }
    // Path ordering numbers (small)
    ctx.fillStyle = '#cbd5e1';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    for (let i=0;i<path.length;i++){
      const n = path[i];
      ctx.fillText(String(i+1), n.x*tileSize + tileSize/2, n.y*tileSize + tileSize/2);
    }

    drawGrid();
    statPath.textContent = String(path.length);
    statBuild.textContent = String(buildSpots.size);
  }

  function canvasToTile(ev){
    const r = canvas.getBoundingClientRect();
    const x = Math.floor((ev.clientX - r.left)/tileSize);
    const y = Math.floor((ev.clientY - r.top)/tileSize);
    if (x < 0 || y < 0 || x >= widthTiles || y >= heightTiles) return null;
    return {x,y};
  }

  function addPathTile(x,y){
    // Avoid duplicates; if exists, remove then push to end
    const idx = path.findIndex(n=>n.x===x && n.y===y);
    if (idx>=0){ path.splice(idx,1); }
    path.push({x,y});
  }

  function removePathTile(x,y){
    const idx = path.findIndex(n=>n.x===x && n.y===y);
    if (idx>=0){ path.splice(idx,1); }
  }

  function toggleBuild(x,y){
    const k = key(x,y);
    if (buildSpots.has(k)) buildSpots.delete(k); else buildSpots.add(k);
  }

  function paintAt(ev){
    const t = canvasToTile(ev);
    if (!t) return;
    if (tool==='path') addPathTile(t.x,t.y);
    else if (tool==='build') toggleBuild(t.x,t.y);
    else if (tool==='erase') { removePathTile(t.x,t.y); buildSpots.delete(key(t.x,t.y)); }
    draw();
  }

  canvas.addEventListener('mousedown', (ev)=>{ isDragging=true; paintAt(ev); });
  canvas.addEventListener('mousemove', (ev)=>{ if(isDragging) paintAt(ev); });
  canvas.addEventListener('mouseup', ()=>{ isDragging=false; });
  canvas.addEventListener('mouseleave', ()=>{ isDragging=false; });

  document.querySelectorAll('.builder-tools .tool').forEach(btn=>{
    btn.addEventListener('click', ()=> setTool(btn.dataset.tool));
  });

  document.getElementById('apply-size').addEventListener('click', ()=>{
    widthTiles = Math.max(5, Math.min(80, parseInt(widthEl.value,10)||30));
    heightTiles = Math.max(5, Math.min(60, parseInt(heightEl.value,10)||20));
    resizeCanvas();
  });
  document.getElementById('clear-path').addEventListener('click', ()=>{ path.length=0; draw(); });
  document.getElementById('clear-builds').addEventListener('click', ()=>{ buildSpots.clear(); draw(); });
  document.getElementById('clear-all').addEventListener('click', ()=>{ path.length=0; buildSpots.clear(); draw(); });

  function getCSRF(){
    const m = document.cookie.match(/csrftoken=([^;]+)/); return m? m[1] : '';
  }

  document.getElementById('save-map').addEventListener('click', async ()=>{
    const payload = {
      name: nameEl.value || 'New Map',
      width: widthTiles,
      height: heightTiles,
      path: path.map(p=>({x:p.x,y:p.y})),
      buildSpots: Array.from(buildSpots).map(k=>fromKey(k)),
    };
    const resp = await fetch('/td-now/api/maps/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRF() },
      body: JSON.stringify(payload),
    });
    if (resp.ok){
      const data = await resp.json();
      alert('Saved map id: '+data.id);
      loadedMapId = data.id;
      await populateLoadList();
    } else {
      const txt = await resp.text();
      alert('Save failed: '+txt);
    }
  });

  document.getElementById('update-map').addEventListener('click', async ()=>{
    if (!loadedMapId) { alert('Load a map first.'); return; }
    const payload = {
      name: nameEl.value || 'Map',
      width: widthTiles,
      height: heightTiles,
      path: path.map(p=>({x:p.x,y:p.y})),
      buildSpots: Array.from(buildSpots).map(k=>fromKey(k)),
    };
    const resp = await fetch(`/td-now/api/maps/${loadedMapId}/`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRF() },
      body: JSON.stringify(payload)
    });
    if (resp.ok){
      alert('Map updated.');
      await populateLoadList();
    } else {
      alert('Update failed: '+ await resp.text());
    }
  });

  async function populateLoadList(){
    const res = await fetch('/td-now/api/levels/');
    let maps = [];
    try { maps = await res.json(); } catch (e) { maps = []; }
    loadSel.innerHTML = '';
    maps.forEach(m => {
      const o = document.createElement('option');
      o.value = m.id; o.textContent = `${m.name} (${m.width_tiles}x${m.height_tiles})`;
      loadSel.appendChild(o);
    });
    if (loadedMapId) loadSel.value = String(loadedMapId);
  }

  loadBtn.addEventListener('click', async ()=>{
    const id = parseInt(loadSel.value,10);
    if (!id) return;
    const res = await fetch(`/td-now/api/levels/${id}/`);
    const lvl = await res.json();
    loadedMapId = id;
    nameEl.value = lvl.name;
    widthTiles = lvl.width; heightTiles = lvl.height;
    path.length = 0; lvl.path.forEach(p => path.push({x:p.x,y:p.y}));
    buildSpots.clear(); lvl.buildSpots.forEach(s => buildSpots.add(key(s.x,s.y)));
    widthEl.value = widthTiles; heightEl.value = heightTiles;
    resizeCanvas();
  });

  resetBtn.addEventListener('click', ()=>{
    loadedMapId = null;
    nameEl.value = 'New Map';
    widthTiles = 30; heightTiles = 20; widthEl.value = 30; heightEl.value = 20;
    path.length=0; buildSpots.clear();
    resizeCanvas();
  });

  // initial
  resizeCanvas();
  populateLoadList();
})();
