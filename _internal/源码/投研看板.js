/* 缓存阅读与受控主题更新，不提供聊天、选股或交易。 */
(()=>{
 const responses=new Map(),etags=new Map();
 let focusReader=false;
 let mode='analysis',selected={topic:'market_a'},index=null,seq=0,shownHash='',metaHash='',busy=false,newsLimit=30;
 const labels={market_a:'A股市场',overseas:'海外市场',capital:'资金观察',events:'事件与政策',sector:'行业专题'};
 const url=s=>{try{const u=new URL(s);return ['http:','https:'].includes(u.protocol)&&!u.username&&!u.password?u.href:null}catch{return null}};
 function markdown(value){
  const inline=s=>esc(s).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,(_,label,href)=>url(href.replace(/&amp;/g,'&'))?`<a href="${esc(url(href.replace(/&amp;/g,'&')))}" target="_blank" rel="noopener noreferrer" title="供应商引用，未核验">${label}</a>`:label);
  let out='',table=false,code=false,list=false;
  for(const line of String(value||'').split('\n')){
   if(/^```/.test(line)){if(table){out+='</table></div>';table=false}if(list){out+='</ul>';list=false}out+=code?'</code></pre>':'<pre><code>';code=!code;continue}
   if(code){out+=esc(line)+'\n';continue}
   if(/^\s*\|/.test(line)){if(/^\s*\|[\s:|\-]+\|?\s*$/.test(line))continue;if(list){out+='</ul>';list=false}if(!table){out+='<div class="scroll"><table>';table=true}out+='<tr>'+line.trim().replace(/^\||\|$/g,'').split('|').map(c=>'<td>'+inline(c.trim())+'</td>').join('')+'</tr>';continue}
   if(table){out+='</table></div>';table=false}
   if(/^\s*[-*]\s+/.test(line)){if(!list){out+='<ul>';list=true}out+='<li>'+inline(line.replace(/^\s*[-*]\s+/,''))+'</li>';continue}
   if(list){out+='</ul>';list=false}
   out+=/^#{1,6}\s/.test(line)?'<h3>'+inline(line.replace(/^#{1,6}\s+/,''))+'</h3>':line.trim()?'<p>'+inline(line)+'</p>':'';
  }return out+(table?'</table></div>':'')+(list?'</ul>':'')+(code?'</code></pre>':'');
 }
 async function api(query={}){
  if(!localMode){const all=d?.research||{documents:{},jobs:{}};const docs=Object.values(all.documents||{});if(!query.topic)return {documents:docs,jobs:Object.values(all.jobs||{}),configured:false};return {document:docs.find(v=>v.key===key(query)),job:null,configured:false}}
  const k=new URLSearchParams(query).toString(),headers={'X-Dashboard-Token':localToken};if(etags.has(k))headers['If-None-Match']=etags.get(k);
  const r=await fetch('/api/research?'+k,{headers});if(r.status===304)return responses.get(k);if(!r.ok)throw Error('本机资料暂不可用');const value=await r.json();responses.set(k,value);etags.set(k,r.headers.get('ETag'));return value;
 }
 const key=v=>v.topic+':'+(v.symbol||v.sector||'market');
 function inputs(){$('research-sector').hidden=selected.topic!=='sector';$('research-funds').hidden=selected.topic!=='capital'}
 function status(job){return job?.state==='queued'?'排队中':job?.state==='running'?'后台分析中，可继续浏览其他页面':job?.state==='failed'?(job.error||'本轮未更新，保留旧资料'):job?.cached?'已复用缓存':job?.state==='succeeded'?'本主题已更新':''}
 function show(doc,job,configured){
  $('research-job').textContent=status(job)||(!configured?(localMode?'未配置华泰密钥，可阅读已有资料与快讯':'离线快照，仅支持阅读'):'');
  $('research-refresh').disabled=!localMode||!configured||!labels[selected.topic]||['queued','running'].includes(job?.state)||(['product','sector'].includes(selected.topic)&&!selected.symbol&&!selected.sector);
  $('research-funds').disabled=!localMode||!configured||!(s?.positions||[]).length;
  const title=doc?.title||labels[selected.topic]||'分析资料';$('research-title').textContent=title;
  $('huatai-state').textContent=doc?'获取 '+date(doc.retrieved_at)+' · '+(doc.reported_as_of?'报告数据日 '+doc.reported_as_of:'正文数据日待核')+(doc.truncated?' · 正文已截断':''):'';
  $('research-source').hidden=!doc;
  if(!doc){if(shownHash!=='empty'){$('huatai-docs').innerHTML='<div class="empty">暂无本主题资料</div>';shownHash='empty'}return}
  const hash=doc.content_hash||doc.answer;
  if(shownHash!==hash){$('huatai-docs').innerHTML=doc.structured_data?`<table><tr><td>产品</td><td>${esc(doc.subject?.name||doc.subject?.symbol)}</td></tr><tr><td>当日主力净流入</td><td>${esc(doc.structured_data.net_inflow_yuan)} 元</td></tr><tr><td>数据日</td><td>${esc(doc.structured_data.date)}</td></tr></table>`:markdown(doc.answer);shownHash=hash}
  $('research-source-body').textContent=[doc.source||'华泰分析资料','供应商引用链接未核验',doc.subject?.classification||'',doc.query||'旧资料未记录查询'].filter(Boolean).join('\n');
 }
 function renderList(meta){
  const rows=(meta.documents||[]).filter(v=>labels[v.topic]||(v.topic==='legacy'&&['events','flows'].includes(v.id))),jobs=new Map((meta.jobs||[]).map(j=>[j.key,j])),hash=JSON.stringify(rows.map(v=>[v.key,v.content_hash,jobs.get(v.key)?.state]));if(hash===metaHash)return;metaHash=hash;
  $('research-list').innerHTML=rows.length?rows.map(v=>`<button type="button" data-report="${esc(v.key)}"><span>${esc(v.title)}</span><small>${esc(date(v.retrieved_at))} · ${jobs.get(v.key)?.state==='failed'?'旧文保留':jobs.get(v.key)?.state==='running'?'更新中':'已缓存'}</small></button>`).join(''):'<p class="hint">尚无分析资料</p>';
 }
 async function news(){const ds=await MarketDashboard.read('news');$('news-state').textContent=ds.source_as_of?date(ds.source_as_of):'时间待核';
  const list=ds.data||[],html=list.slice(0,newsLimit).map(v=>`<article class="news-item"><small>${esc(v.source||'')} · ${esc(v.published_at?date(v.published_at):'时间待核')}</small><details><summary>${esc(v.title)}</summary><p>${esc(v.summary||v.title)}</p>${url(v.url)?`<a href="${esc(url(v.url))}" target="_blank" rel="noopener noreferrer">来源</a>`:''}</details></article>`).join('');
  if($('news-list').dataset.rev!==ds.revision+':'+newsLimit){$('news-list').innerHTML=html||'<div class="empty">暂无快讯</div>';$('news-list').dataset.rev=ds.revision+':'+newsLimit}$('news-more').hidden=list.length<=newsLimit;
 }
 async function update(){if(busy||!d||DashboardNavigation.active!=='research')return;busy=true;const round=seq;try{
  if(mode==='news'){await news();return}inputs();const [meta,detail]=await Promise.all([api(),api(selected)]);if(round!==seq)return;index=meta;renderList(meta);show(detail.document,detail.job,meta.configured);
  if(focusReader){focusReader=false;if(matchMedia('(max-width:800px)').matches)$('huatai-panel').scrollIntoView({block:'start'})}
  for(const button of $('research-list').querySelectorAll('[data-report]'))button.classList.toggle('on',button.dataset.report===key(selected));
 }catch(error){$('research-job').textContent=error.message}finally{busy=false;if(round!==seq)queueMicrotask(update)}}
 function open(v){if(!labels[v.topic]&&v.topic!=='legacy')return;focusReader=true;selected={...v};seq++;shownHash='';$('research-topic').value=selected.topic==='legacy'?'events':selected.topic;mode='analysis';switchView();if($('product-dialog').open)$('product-close').click();DashboardNavigation.go('research');if(!busy)update();else setTimeout(update,100)}
 function switchView(){seq++;$('research-analysis').hidden=mode!=='analysis';$('news-panel').hidden=mode!=='news';document.querySelectorAll('[data-research-view]').forEach(b=>b.classList.toggle('on',b.dataset.researchView===mode));update()}
 async function submit(v){const r=await fetch('/api/research/refresh',{method:'POST',headers:{'X-Dashboard-Token':localToken,'Content-Type':'application/json'},body:JSON.stringify(v)});const data=await r.json();if(!r.ok)throw Error(data.error||'未能启动分析');return data}
 $('research-back').onclick=()=>$('research-topic').scrollIntoView({block:'center'});
 $('research-refresh').onclick=async()=>{try{$('research-refresh').disabled=true;const job=await submit(selected);$('research-job').textContent=status(job);update()}catch(e){$('research-job').textContent=e.message;$('research-refresh').disabled=false}};
 $('research-funds').onclick=async()=>{try{$('research-funds').disabled=true;for(const p of (s?.positions||[]).slice(0,6))await submit({topic:'fund',symbol:p.key});$('research-job').textContent='持仓资金在后台更新，完成后市场页自动显示'}catch(e){$('research-job').textContent=e.message}};
 $('research-topic').onchange=()=>{const topic=$('research-topic').value;open({topic,...(topic==='sector'&&$('research-sector').value?{sector:$('research-sector').value}:{})})};
 $('research-sector').onchange=()=>open({topic:'sector',sector:$('research-sector').value});
 $('research-list').onclick=e=>{const b=e.target.closest('[data-report]');const row=index?.documents.find(v=>v.key===b?.dataset.report);if(row)open({topic:row.topic,...(row.topic==='legacy'?{symbol:row.id}:row.subject?.symbol?{symbol:row.subject.symbol}:row.subject?.sector?{sector:row.subject.sector}:{})})};
 $('news-more').onclick=()=>{newsLimit+=30;news().catch(e=>{$('news-state').textContent=e.message})};
 document.addEventListener('click',e=>{const v=e.target.closest('[data-research-view]');if(v){mode=v.dataset.researchView;switchView()}const sector=e.target.closest('[data-research-sector]');if(sector)open({topic:'sector',sector:sector.dataset.researchSector})});
 document.addEventListener('keydown',e=>{const b=e.target.closest('[data-research-sector]');if(e.key==='Enter'&&b)open({topic:'sector',sector:b.dataset.researchSector})});
 document.addEventListener('dashboard:page',()=>{if(DashboardNavigation.active==='research'){MarketDashboard.read('sectors',{group:'industry'}).then(ds=>{const html='<option value="">选择行业</option>'+(ds.data||[]).map(v=>`<option value="${esc(v.id)}">${esc(v.name)}</option>`).join('');if($('research-sector').innerHTML!==html){$('research-sector').innerHTML=html;$('research-sector').value=selected.sector||''}}).catch(()=>{});update()}});
 setInterval(()=>{if(!document.hidden)update()},5000);
 window.ResearchDashboard={update,markdown,open,read:api,refresh:submit,status};
})();
