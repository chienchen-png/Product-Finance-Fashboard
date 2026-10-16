/* 市场展示：只读本机API，无AI/策略/交易调用。 */
(()=>{
  const cache=new Map(),tags=new Map();let active='account',busy=false,opened=null;
  const dash=v=>v==null?'—':fmt(v),pct=v=>v==null?'—':rate(Number(v)*100);
  const status=v=>({ok:'已更新',stale:'已过期',partial:'部分数据',unknown:'时间待核',unavailable:'暂无数据'}[v]||'待核');
  const money=v=>v==null?'—':Math.abs(Number(v))>=1e8?(Number(v)/1e8).toFixed(2)+'亿':Math.abs(Number(v))>=1e4?(Number(v)/1e4).toFixed(2)+'万':fmt(v);
  async function read(section,params={}){
    const query=new URLSearchParams({section,...params}),key=query.toString();
    if(!localMode){const suffix=section==='ranks'?':'+(params.product_type||'stock')+':'+(params.sort||'up'):section==='sectors'?':'+(params.group||'industry'):params.symbol?':'+params.symbol:'';return d?.market_sections?.[section+suffix]||{status:'unavailable',data:[],reason:'离线快照未包含该数据'}}
    const headers={'X-Dashboard-Token':localToken};if(tags.has(key))headers['If-None-Match']=tags.get(key);
    const r=await fetch('/api/market?'+query,{headers});if(r.status===304)return cache.get(key);
    if(!r.ok)throw Error('数据暂不可用');const data=await r.json();tags.set(key,r.headers.get('ETag'));cache.set(key,data);return data;
  }
  function stamp(id,ds){const el=$(id);el.textContent=status(ds.status)+(ds.source_as_of?' · '+date(ds.source_as_of):'');el.title=[ds.source,ds.reason,ds.coverage?.scope].filter(Boolean).join(' · ')}
  function links(items){return items.length?items.map(v=>`<article class="news-item"><small>${esc(v.source||'')} · ${esc(v.published_at?date(v.published_at):v.announcement_date||'时间待核')}</small>${v.url&&/^https?:\/\//.test(v.url)?`<a href="${esc(v.url)}" target="_blank" rel="noopener noreferrer">${esc(v.title)}</a>`:`<span>${esc(v.title)}</span>`}</article>`).join(''):'<div class="empty">暂无数据</div>'}
  async function overview(){const ds=await read('overview');$('index-strip').innerHTML=(ds.data||[]).filter(v=>v.product_type!=='holding').map(v=>`<button class="index-card" data-product="${esc(v.symbol)}"><small>${esc(v.display_name||v.name)}</small><b>${price(v.price)}</b><span class="${cls(v.change_pct)}">${pct(v.change_pct)}</span><small title="${esc(v.source||'')}">${esc(v.source_as_of?date(v.source_as_of):v.source_local_time||'行情时间待核')} · ${status(v.status)}</small></button>`).join('')||'<div class="empty">市场数据等待更新</div>';}
  async function ranks(){const ds=await read('ranks',{product_type:$('rank-type').value,sort:$('rank-sort').value});stamp('rank-state',ds);$('rank-rows').innerHTML=(ds.data||[]).map(v=>`<tr tabindex="0" data-product="${esc(v.symbol)}"><td>${esc(v.name)}<br><small>${esc(v.symbol)}</small></td><td>${price(v.price)}</td><td class="${cls(v.change_pct)}">${pct(v.change_pct)}</td><td>${money(v.amount)}</td><td>${pct(v.turnover_rate)}</td></tr>`).join('')||'<tr><td colspan="5" class="empty">暂无排行</td></tr>';}
  async function sectors(){const ds=await read('sectors',{group:$('sector-type').value});stamp('sector-state',ds);const rows=ds.data||[];const mode=$('sector-view').value;
    $('sector-table').hidden=mode!=='table';$('sector-map').hidden=mode==='table';
    $('sector-rows').innerHTML=rows.map(v=>`<tr><td>${esc(v.name)}</td><td class="${cls(v.change_pct)}">${pct(v.change_pct)}</td><td>${money(v.amount)}</td><td>${v.member_count??'—'}</td></tr>`).join('')||'<tr><td colspan="4" class="empty">暂无板块</td></tr>';
    if(mode!=='table')chart('sector-map')?.setOption({tooltip:{...tooltipBase,formatter:p=>`${esc(p.name)}${tipRows([['涨跌',pct(p.data.change_pct)],['成交额',money(p.data.amount)],['成分数量',dash(p.data.member_count)]])}`},series:[{type:'treemap',roam:false,nodeClick:false,breadcrumb:{show:false},label:{formatter:p=>p.name+'\n'+pct(p.data.change_pct)},data:rows.map(v=>({...v,name:v.name,value:Math.max(Math.abs(Number(v.amount)||0),1),itemStyle:{color:Number(v.change_pct)>=0?'#c66a60':'#398d77'}}))}]},true);
  }
  async function news(){const ds=await read('news');stamp('news-state',ds);$('news-list').innerHTML=links(ds.data||[])}
  let detailRevision='';
  async function update(){if(busy||!d)return;busy=true;try{
    if(active==='market')await Promise.allSettled([overview(),ranks(),sectors(),news()]);
    if(opened&&$('product-dialog').open){
      const state=kv[opened.key],has=state&&klineCache.get(opened.key)?.[state.g];
      if(!has||detailRevision!==d.kline_revision){
        detailRevision=d.kline_revision;await activateDetail(opened,'market');
      }
    }
  }finally{busy=false}}
  async function openProduct(symbol){
    const values=[...(s?.positions||[]).map(p=>({...p,symbol:p.key})),...[...cache.values()].flatMap(ds=>Array.isArray(ds.data)?ds.data:[])];
    const v=values.find(p=>p.symbol===symbol);if(!v)return;
    opened={...v,key:symbol,code:symbol.split(':')[1],exchange:symbol.split(':')[0],average_cost:v.average_cost??null};
    $('product-title').textContent=(v.name||symbol)+' · '+symbol;
    window.DashboardCharts?.drop('k-market');
    $('product-news').hidden=true;$('product-news').innerHTML='';
    $('product-body').innerHTML=detail(opened,'market');$('product-dialog').showModal();
    await activateDetail(opened,'market');
    const extra=await Promise.allSettled([Promise.resolve({data:[]}),d?.market_capabilities?.nav?read('nav',{symbol}):Promise.resolve({data:[]})]);
    const ann=extra[0].status==='fulfilled'?extra[0].value.data:[];
    const nav=extra[1].status==='fulfilled'?extra[1].value.data?.[0]:null;
    const extraHtml=(nav?`<p class="hint">披露净值 ${price(nav.unit_nav)} · ${esc(nav.date)}（非实时IOPV）</p>`:'')+((ann||[]).length?links(ann):'');
    $('product-news').innerHTML=extraHtml;$('product-news').hidden=!extraHtml;
  }
  $('page-tabs').addEventListener('click',e=>{const b=e.target.closest('[data-page]');if(!b)return;active=b.dataset.page;for(const name of ['account','market']){$(name+'-page').hidden=active!==name;document.querySelector(`[data-page="${name}"]`).setAttribute('aria-selected',String(active===name))}charts.forEach(c=>c.resize());update()});
  for(const id of ['rank-type','rank-sort','sector-type','sector-view'])$(id).addEventListener('change',update);
  $('market-page').addEventListener('click',e=>{const b=e.target.closest('[data-product]');if(b)openProduct(b.dataset.product)});
  $('market-page').addEventListener('keydown',e=>{if(e.key==='Enter'){const b=e.target.closest('[data-product]');if(b)openProduct(b.dataset.product)}});
  $('product-close').onclick=()=>{window.DashboardCharts?.drop('k-market');$('product-dialog').close()};
  $('product-body').addEventListener('click',e=>{const b=e.target.closest('.kbtn');if(!b||!opened)return;const state=kv[opened.key];if(b.dataset.t==='g')state.g=b.dataset.v;else state.range=b.dataset.v;state.zoom=null;activateDetail(opened,'market')});
  setInterval(()=>{if(!document.hidden)update()},5000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)update()});
  window.MarketDashboard={update,read,openProduct};
})();
