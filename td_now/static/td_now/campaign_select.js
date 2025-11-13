// Campaign selection page
(function(){
  async function init(){
    const [cRes, mRes] = await Promise.all([
      fetch('/td-now/api/campaigns/'),
      fetch('/td-now/api/levels/'),
    ]);
    const campaigns = await cRes.json();
    const maps = await mRes.json();

    const cList = document.getElementById('campaign-list');
    const mList = document.getElementById('map-list');
    if (cList) {
      cList.innerHTML = '';
      campaigns.forEach(c => {
        const row = document.createElement('div'); row.className = 'row';
        const name = document.createElement('div'); name.className = 'name'; name.textContent = `${c.name}`;
        const play = document.createElement('a'); play.className='btn'; play.textContent='Play'; play.href = `/td-now/play/?campaign=${c.id}`;
        const edit = document.createElement('a'); edit.className='btn gray'; edit.textContent='Edit'; edit.href = `/td-now/campaign-builder/?id=${c.id}`;
        row.append(name, play, edit);
        cList.appendChild(row);
      });
    }
    if (mList) {
      mList.innerHTML = '';
      maps.forEach(m => {
        const row = document.createElement('div'); row.className = 'row';
        const name = document.createElement('div'); name.className = 'name'; name.textContent = `${m.name} (${m.width_tiles}x${m.height_tiles})`;
        const play = document.createElement('a'); play.className='btn'; play.textContent='Play'; play.href = `/td-now/play/?map=${m.id}`;
        const inf = document.createElement('a'); inf.className='btn green'; inf.style.marginLeft = '0.5rem'; inf.textContent='Infinite'; inf.href = `/td-now/play/?map=${m.id}&infinite=1`;
        row.append(name, play, inf);
        mList.appendChild(row);
      });
    }
  }
  init();
})();
