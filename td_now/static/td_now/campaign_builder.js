// Campaign Builder UI
(function(){
  const stagesEl = document.getElementById('cb-stages');
  if (!stagesEl) return;

  const nameEl = document.getElementById('cb-name');
  const moneyEl = document.getElementById('cb-money');
  const livesEl = document.getElementById('cb-lives');
  const addStageBtn = document.getElementById('add-stage');
  const saveBtn = document.getElementById('save-campaign');
  // Load existing campaigns
  let currentId = null;
  let campaigns = [];

  let maps = [];
  let enemies = [];

  async function fetchData(){
    const [mapsRes, ennemRes, campsRes] = await Promise.all([
      fetch('/td-now/api/levels/'),
      fetch('/td-now/api/enemies/'),
      fetch('/td-now/api/campaigns/'),
    ]);
    maps = await mapsRes.json();
    enemies = await ennemRes.json();
    campaigns = await campsRes.json();
  }

  function option(value, text){
    const o = document.createElement('option');
    o.value = value; o.textContent = text; return o;
  }

  function addGroupRow(groupsEl){
    const row = document.createElement('div'); row.className = 'group';
    const sel = document.createElement('select');
    enemies.forEach(e => sel.appendChild(option(e.id, e.name)));
    const count = document.createElement('input'); count.type='number'; count.value='10';
    const interval = document.createElement('input'); interval.type='number'; interval.step='0.1'; interval.value='0.8';
    const delay = document.createElement('input'); delay.type='number'; delay.step='0.1'; delay.value='0';
    const del = document.createElement('button'); del.className='btn red'; del.textContent='Delete';
    del.addEventListener('click', ()=>{ row.remove(); });
    row.append(sel, count, interval, delay, del);
    groupsEl.appendChild(row);
  }

  function addWaveBlock(wavesEl, waveNum){
    const div = document.createElement('div'); div.className='wave';
    const title = document.createElement('div'); title.style.marginBottom='.35rem'; title.textContent = 'Wave ' + waveNum;
    const groups = document.createElement('div'); groups.className='groups';
    const tools = document.createElement('div'); tools.className='stage-tools';
    const addGroup = document.createElement('button'); addGroup.className='btn'; addGroup.textContent='Add Group';
    addGroup.addEventListener('click', ()=> addGroupRow(groups));
    tools.append(addGroup);
    div.append(title, groups, tools);
    wavesEl.appendChild(div);
    addGroupRow(groups);
  }

  function addStage(){
    const idx = stagesEl.children.length + 1;
    const st = document.createElement('div'); st.className='stage';
    const h = document.createElement('h4'); h.textContent = 'Stage ' + idx;

    const mapField = document.createElement('div'); mapField.className='cb-field';
    const mapLbl = document.createElement('label'); mapLbl.textContent='Map';
    const mapSel = document.createElement('select'); maps.forEach(m => mapSel.appendChild(option(m.id, `${m.name} (${m.width_tiles}x${m.height_tiles})`)));
    mapField.append(mapLbl, mapSel);

    const overrideRow = document.createElement('div'); overrideRow.className='cb-flex';
    const omField = document.createElement('div'); omField.className='cb-field';
    const omLbl = document.createElement('label'); omLbl.textContent='Start Money (override)';
    const omInput = document.createElement('input'); omInput.type='number'; omInput.placeholder='leave blank';
    omField.append(omLbl, omInput);
    const olField = document.createElement('div'); olField.className='cb-field';
    const olLbl = document.createElement('label'); olLbl.textContent='Start Lives (override)';
    const olInput = document.createElement('input'); olInput.type='number'; olInput.placeholder='leave blank';
    olField.append(olLbl, olInput);
    overrideRow.append(omField, olField);

    const msgField = document.createElement('div'); msgField.className='cb-field';
    const msgLbl = document.createElement('label'); msgLbl.textContent='Stage Message';
    const msgArea = document.createElement('textarea'); msgArea.rows=2; msgArea.placeholder='Shown between stages';
    msgField.append(msgLbl, msgArea);

    const waves = document.createElement('div'); waves.className='waves';
    addWaveBlock(waves, 1);

    const tools = document.createElement('div'); tools.className='stage-tools';
    const addWave = document.createElement('button'); addWave.className='btn'; addWave.textContent='Add Wave';
    addWave.addEventListener('click', ()=>{ addWaveBlock(waves, waves.children.length + 1); });
    const delStage = document.createElement('button'); delStage.className='btn gray'; delStage.textContent='Remove Stage';
    delStage.addEventListener('click', ()=>{ st.remove(); reindexStages(); });
    tools.append(addWave, delStage);

    st.append(h, mapField, overrideRow, msgField, waves, tools);
    stagesEl.appendChild(st);
  }

  function reindexStages(){
    Array.from(stagesEl.children).forEach((st, i)=>{
      const h = st.querySelector('h4'); if (h) h.textContent = 'Stage ' + (i+1);
    });
  }

  function collect(){
    const payload = {
      name: nameEl.value || 'New Campaign',
      startMoney: parseInt(moneyEl.value,10)||200,
      startLives: parseInt(livesEl.value,10)||20,
      stages: [],
    };
    Array.from(stagesEl.children).forEach((st, i)=>{
      const mapId = parseInt(st.querySelector('select').value,10);
      const inputs = st.querySelectorAll('input');
      const om = inputs[0].value === '' ? null : parseInt(inputs[0].value,10);
      const ol = inputs[1].value === '' ? null : parseInt(inputs[1].value,10);
      const msg = st.querySelector('textarea').value || '';
      const wavesEl = st.querySelector('.waves');
      const waves = [];
      Array.from(wavesEl.children).forEach((w, wi)=>{
        const groupsEl = w.querySelector('.groups');
        const groups = [];
        Array.from(groupsEl.children).forEach((row)=>{
          if (!row.classList.contains('group')) return;
          const [sel,count,interval,delay] = row.querySelectorAll('select, input');
          groups.push({
            typeId: parseInt(sel.value,10),
            count: parseInt(count.value,10)||1,
            spawnInterval: parseFloat(interval.value)||1.0,
            startDelay: parseFloat(delay.value)||0.0,
          });
        });
        waves.push({ number: wi+1, groups });
      });
      payload.stages.push({
        mapId, startMoneyOverride: om, startLivesOverride: ol, message: msg, waves
      });
    });
    return payload;
  }

  function getCSRF(){ const m = document.cookie.match(/csrftoken=([^;]+)/); return m? m[1]:''; }

  async function save(){
    const payload = collect();
    const res = await fetch('/td-now/api/campaigns/create/', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRF() },
      body: JSON.stringify(payload)
    });
    if (res.ok){
      const data = await res.json();
      alert('Saved campaign id: '+data.id+". Play: /td-now/?campaign="+data.id);
    } else {
      const t = await res.text(); alert('Save failed: '+t);
    }
  }

  addStageBtn.addEventListener('click', addStage);
  saveBtn.addEventListener('click', save);

  // Load support via query param id
  async function maybeLoadFromQuery(){
    const u = new URL(window.location.href);
    const id = parseInt(u.searchParams.get('id')||'',10);
    if (!id) { addStage(); return; }
    currentId = id;
    await loadCampaign(id);
  }

  async function loadCampaign(id){
    const res = await fetch(`/td-now/api/campaigns/${id}/`);
    if (!res.ok) { addStage(); return; }
    const c = await res.json();
    nameEl.value = c.name;
    moneyEl.value = c.startMoney;
    livesEl.value = c.startLives;
    stagesEl.innerHTML = '';
    c.stages.forEach(st => addStageFromData(st, maps));
  }

  function setSelectValue(sel, val){ Array.from(sel.options).forEach(o=>{ if (String(o.value)===String(val)) sel.value=String(val); }); }

  function addStageFromData(st, maps){
    addStage();
    const stageDiv = stagesEl.lastElementChild;
    const mapSel = stageDiv.querySelector('select'); setSelectValue(mapSel, st.map.id);
    const inputs = stageDiv.querySelectorAll('input');
    if (st.startMoneyOverride!=null) inputs[0].value = String(st.startMoneyOverride); else inputs[0].value='';
    if (st.startLivesOverride!=null) inputs[1].value = String(st.startLivesOverride); else inputs[1].value='';
    stageDiv.querySelector('textarea').value = st.message || '';
    const wavesContainer = stageDiv.querySelector('.waves'); wavesContainer.innerHTML='';
    (st.waves || []).forEach((w,i)=>{
      addWaveBlock(wavesContainer, i+1);
      const waveDiv = wavesContainer.lastElementChild;
      const groups = waveDiv.querySelector('.groups'); groups.innerHTML='';
      (w.groups||[]).forEach(g=>{
        const row = document.createElement('div'); row.className='group';
        const sel = document.createElement('select'); enemies.forEach(e => sel.appendChild(option(e.id, e.name))); setSelectValue(sel, g.typeId);
        const count = document.createElement('input'); count.type='number'; count.value=String(g.count||1);
        const interval = document.createElement('input'); interval.type='number'; interval.step='0.1'; interval.value=String(g.spawnInterval||1.0);
        const delay = document.createElement('input'); delay.type='number'; delay.step='0.1'; delay.value=String(g.startDelay||0);
        const del = document.createElement('button'); del.className='btn red'; del.textContent='Delete'; del.addEventListener('click', ()=> row.remove());
        row.append(sel,count,interval,delay,del);
        groups.appendChild(row);
      });
    });
  }

  async function save(){
    const payload = collect();
    const isUpdate = !!currentId;
    const url = isUpdate ? `/td-now/api/campaigns/${currentId}/update/` : '/td-now/api/campaigns/create/';
    const res = await fetch(url, {
      method: isUpdate ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRF() },
      body: JSON.stringify(payload)
    });
    if (res.ok){
      const data = await res.json();
      currentId = data.id;
      alert('Saved campaign id: '+data.id+". Play: /td-now/play/?campaign="+data.id);
    } else {
      const t = await res.text(); alert('Save failed: '+t);
    }
  }

  fetchData().then(()=> maybeLoadFromQuery());
})();
