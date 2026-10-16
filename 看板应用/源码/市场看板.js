/* 市场展示：只读本机API，无AI/策略/交易调用。 */
(()=>{
  const cache=new Map(),tags=new Map();let active='account',busy=false,opened=null,sectorDataset=null;
  const dash=v=>v==null?'—':fmt(v),pct=v=>v==null?'—':rate(Number(v)*100);
  const status=v=>({ok:'已更新',stale:'已过期',partial:'部分数据',unknown:'时间待核',unavailable:'暂无数据'}[v]||'待核');
  const money=v=>v==null?'—':Math.abs(Number(v))>=1e8?(Number(v)/1e8).toFixed(2)+'亿':Math.abs(Number(v))>=1e4?(Number(v)/1e4).toFixed(2)+'万':fmt(v);
  async function read(section,params={}){
    const query=new URLSearchParams({section,...params}),key=query.toString();
    if(!localMode){const suffix=section==='ranks'?':'+(params.product_type||'stock')+':'+(params.sort||'up'):section==='sectors'?':'+(params.group||'industry'):params.symbol?':'+params.symbol:'';const value=d?.market_sections?.[section+suffix]||{status:'unavailable',data:[],reason:'离线快照未包含该数据'};cache.set(key,value);return value}
    const headers={'X-Dashboard-Token':localToken};if(tags.has(key))headers['If-None-Match']=tags.get(key);
    const r=await fetch('/api/market?'+query,{headers});if(r.status===304)return cache.get(key);
    if(!r.ok)throw Error('数据暂不可用');const data=await r.json();tags.set(key,r.headers.get('ETag'));cache.set(key,data);return data;
  }
  function stamp(id,ds){const el=$(id);el.textContent=status(ds.status)+(ds.source_as_of?' · '+date(ds.source_as_of):'');el.title=[ds.source,ds.reason,ds.coverage?.scope].filter(Boolean).join(' · ')}
  function replaceHTML(id,html){const el=$(id);if(el.innerHTML===html)return;const parent=el.closest('.scroll,.news-list'),top=parent?.scrollTop,left=parent?.scrollLeft;el.innerHTML=html;if(parent){parent.scrollTop=top;parent.scrollLeft=left}}
  function sectorColor(value){
    if(value==null||!Number.isFinite(Number(value)))return '#dce3e6';
    const n=Number(value),t=Math.min(Math.abs(n)/.05,1),base=[237,241,242],end=n<0?[25,137,105]:[198,85,73];
    return 'rgb('+base.map((v,i)=>Math.round(v+(end[i]-v)*t)).join(',')+')';
  }
  function arrangeIndices(){
    const strip=$('index-strip'),count=strip.querySelectorAll('.index-card').length,width=strip.clientWidth;
    if(!count||!width)return;
    const gap=width<600?8:10,capacity=Math.max(1,Math.floor((width+gap)/(width<600?158:182))),columns=Math.ceil(count/Math.ceil(count/capacity));
    strip.style.setProperty('--index-columns',columns);
  }
  const indexObserver=typeof ResizeObserver==='undefined'?null:new ResizeObserver(arrangeIndices);
  indexObserver?.observe($('index-strip'));
  function links(items){return items.length?items.map(v=>`<article class="news-item"><small>${esc(v.source||'')} · ${esc(v.published_at?date(v.published_at):v.announcement_date||'时间待核')}</small>${v.url&&/^https?:\/\//.test(v.url)?`<a href="${esc(v.url)}" target="_blank" rel="noopener noreferrer">${esc(v.title)}</a>`:`<span>${esc(v.title)}</span>`}</article>`).join(''):'<div class="empty">暂无数据</div>'}
  async function overview(){const ds=await read('overview');replaceHTML('index-strip',(ds.data||[]).filter(v=>v.product_type!=='holding'&&v.chart_available!==false).sort((a,b)=>(a.product_type==='index'?0:a.product_type==='fx'||a.product_type==='future'?1:2)-(b.product_type==='index'?0:b.product_type==='fx'||b.product_type==='future'?1:2)).map(v=>`<button class="index-card" data-product="${esc(v.symbol)}"><span class="index-name" title="${esc(v.display_name||v.name)}">${esc(v.display_name||v.name)}</span><b>${price(v.price)}</b><span class="index-change ${cls(v.change_pct)}">${pct(v.change_pct)}</span><small title="${esc(v.source||'')}">${esc(v.source_as_of?date(v.source_as_of):v.source_local_time||'行情时间待核')} · ${status(v.status)}</small></button>`).join('')||'');$('index-strip').hidden=!$('index-strip').querySelector('.index-card');arrangeIndices();}
  async function ranks(){const ds=await read('ranks',{product_type:$('rank-type').value,sort:$('rank-sort').value});stamp('rank-state',ds);$('rank-panel').hidden=!(ds.data||[]).length||ds.error_kind==='permission';if($('rank-panel').hidden)return;replaceHTML('rank-rows',(ds.data||[]).map(v=>`<tr tabindex="0" data-product="${esc(v.symbol)}"><td title="${esc(v.name)}">${esc(v.name)}<br><small>${esc(v.symbol)}</small></td><td>${price(v.price)}</td><td class="${cls(v.change_pct)}">${pct(v.change_pct)}</td><td>${money(v.amount)}</td></tr>`).join('')||'<tr><td colspan="4" class="empty">暂无排行</td></tr>');}
  async function sectors(){const ds=await read('sectors',{group:$('sector-type').value});stamp('sector-state',ds);const rows=ds.data||[];$('sector-panel').hidden=!rows.length||ds.error_kind==='permission';if($('sector-panel').hidden)return;const mode=$('sector-view').value;
    $('sector-table').hidden=mode!=='table';$('sector-map').hidden=mode==='table';$('sector-legend').hidden=mode==='table'||!rows.length;
    replaceHTML('sector-rows',rows.map(v=>`<tr><td>${esc(v.name)}</td><td class="${cls(v.change_pct)}">${pct(v.change_pct)}</td><td>${money(v.amount)}</td><td>${v.member_count??'—'}</td></tr>`).join('')||'<tr><td colspan="4" class="empty">暂无板块</td></tr>');
    if(mode!=='table'){
      const instance=chart('sector-map');
      if(instance&&sectorDataset!==ds){
        instance.setOption({animation:false,title:{show:!rows.length,text:'暂无板块数据',left:'center',top:'middle',textStyle:{fontSize:13,fontWeight:'normal',color:'#647a83'}},tooltip:{...tooltipBase,formatter:p=>`${esc(p.name)}${tipRows([['涨跌',pct(p.data.change_pct)],['成交额',money(p.data.amount)],['成分数量',dash(p.data.member_count)]])}`},series:[{type:'treemap',left:0,right:0,top:0,bottom:0,roam:false,nodeClick:false,breadcrumb:{show:false},visibleMin:16,label:{show:true,fontSize:12,overflow:'truncate',formatter:p=>p.name+'\n'+pct(p.data.change_pct)},upperLabel:{show:false},itemStyle:{borderColor:'#fff',borderWidth:2,gapWidth:2},emphasis:{itemStyle:{borderColor:'#205f53',borderWidth:2}},data:rows.map(v=>({...v,name:v.name,value:Math.max(Math.abs(Number(v.amount)||0),1),itemStyle:{color:sectorColor(v.change_pct)},label:{color:v.change_pct!=null&&Math.abs(Number(v.change_pct))>=.025?'#fff':'#263e47'}}))}]},true);
        sectorDataset=ds;
      }
      instance?.resize();
    }
  }
  async function news(){const ds=await read('news');stamp('news-state',ds);$('news-panel').hidden=!(ds.data||[]).length||ds.error_kind==='permission';if($('news-panel').hidden)return;replaceHTML('news-list',links(ds.data||[]))}
  function researchMarkdown(value){
    const lines=String(value||'').split('\n');let output='',table=false;
    const inline=s=>esc(s).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
    for(const line of lines){
      if(/^\s*\|/.test(line)){
        if(/^\s*\|[\s:|\-]+\|?\s*$/.test(line))continue;
        if(!table){output+='<div class="scroll"><table>';table=true}
        output+='<tr>'+line.trim().replace(/^\||\|$/g,'').split('|').map(c=>'<td>'+inline(c.trim())+'</td>').join('')+'</tr>';continue;
      }
      if(table){output+='</table></div>';table=false}
      output+=/^#{1,6}\s/.test(line)?'<h3>'+inline(line.replace(/^#{1,6}\s+/,''))+'</h3>':line.trim()?'<p>'+inline(line)+'</p>':'';
    }
    return output+(table?'</table></div>':'');
  }
  async function huatai(){
    const ds=await read('huatai');$('huatai-panel').hidden=!(ds.data||[]).length;if($('huatai-panel').hidden)return;
    $('huatai-state').textContent=(ds.pending?'后台更新中':'取数 '+date(ds.retrieved_at))+(ds.errors?.length?' · 部分未更新':'');
    const open=new Set([...document.querySelectorAll('#huatai-docs details[open]')].map(x=>x.dataset.topic));
    replaceHTML('huatai-docs',(ds.data||[]).map(v=>`<details class="research-doc" data-topic="${esc(v.id)}" ${open.has(v.id)?'open':''}><summary>${esc(v.title)} · ${esc(date(v.retrieved_at))}</summary><div class="research-body">${researchMarkdown(v.answer)}</div></details>`).join(''));
  }
  let detailRevision='';
  async function update(){if(busy||!d)return;busy=true;try{
    if(active==='market'){await Promise.allSettled([overview(),ranks(),sectors(),news(),huatai()]);$('market-empty').hidden=Boolean($('index-strip').querySelector('.index-card')||document.querySelector('.market-grid>.panel:not([hidden])'))}
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
  $('page-tabs').addEventListener('click',e=>{const b=e.target.closest('[data-page]');if(!b)return;active=b.dataset.page;document.querySelector('main').classList.toggle('market-layout',active==='market');for(const name of ['account','market']){$(name+'-page').hidden=active!==name;document.querySelector(`[data-page="${name}"]`).setAttribute('aria-selected',String(active===name))}charts.forEach(c=>{const node=c.getDom();if(node.clientWidth&&node.clientHeight)c.resize()});update()});
  for(const id of ['rank-type','rank-sort','sector-type','sector-view'])$(id).addEventListener('change',update);
  $('market-page').addEventListener('click',e=>{const b=e.target.closest('[data-product]');if(b)openProduct(b.dataset.product)});
  $('market-page').addEventListener('keydown',e=>{if(e.key==='Enter'){const b=e.target.closest('[data-product]');if(b)openProduct(b.dataset.product)}});
  $('product-close').onclick=()=>{window.DashboardCharts?.drop('k-market');$('product-dialog').close()};
  $('product-body').addEventListener('click',e=>{const b=e.target.closest('.kbtn');if(!b||!opened)return;const state=kv[opened.key];if(b.dataset.t==='g')state.g=b.dataset.v;else state.range=b.dataset.v;state.zoom=null;activateDetail(opened,'market')});
  setInterval(()=>{if(!document.hidden)update()},5000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)update()});
  window.MarketDashboard={update,read,openProduct,currentProduct:key=>opened?.key===key?opened:null};
})();
