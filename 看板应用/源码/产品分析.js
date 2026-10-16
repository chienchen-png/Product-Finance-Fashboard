/* 产品详情内阅读与按需分析；行情轮询不触发报告生成。 */
(()=>{
 const pending=new Map(),attempted=new Set(),deadlines=new Map();
 const active=panel=>panel.isConnected&&!panel.hidden&&!panel.closest('[hidden]')&&(!panel.closest('dialog')||panel.closest('dialog').open);
 function draw(panel,value,message=''){
  if(!panel.isConnected)return;
  const {document:doc,job,configured}=value;
  panel.querySelector('.analysis-time').textContent=doc?'获取 '+date(doc.retrieved_at)+' · 正文数据日待核':'';
  panel.querySelector('.analysis-state').textContent=message||ResearchDashboard.status(job)||(!configured?(localMode?'未配置华泰密钥，可阅读已有缓存':'离线快照，仅支持阅读'):'');
  panel.querySelector('.analysis-refresh').disabled=!localMode||!configured||['queued','running'].includes(job?.state);
  const body=panel.querySelector('.analysis-body'),hash=doc?(doc.content_hash||doc.answer):'empty';
  if(body.dataset.hash!==hash){body.innerHTML=doc?ResearchDashboard.markdown(doc.answer):'<p class="hint">暂无缓存分析</p>';body.dataset.hash=hash}
  const source=panel.querySelector('.analysis-source');source.hidden=!doc;
  source.querySelector('div').textContent=doc?[doc.source||'华泰分析资料',doc.query||'', '引用链接未核验'].filter(Boolean).join('\n'):'';
 }
 async function read(symbol){
  if(pending.has(symbol))return pending.get(symbol);
  const promise=ResearchDashboard.read({topic:'product',symbol});pending.set(symbol,promise);
  try{return await promise}finally{pending.delete(symbol)}
 }
 async function load(panel,generate=false,refresh=false){
  if(panel.dataset.busy==='true')return;panel.dataset.busy='true';
  const symbol=panel.dataset.analysisPanel;
  try{
   let value=await read(symbol);draw(panel,value);
   if(localMode&&value.configured&&(refresh||generate&&!value.document&&!attempted.has(symbol))){
    attempted.add(symbol);
    if(!['queued','running'].includes(value.job?.state)){
     panel.querySelector('.analysis-state').textContent='正在提交分析…';panel.querySelector('.analysis-refresh').disabled=true;
     const job=await ResearchDashboard.refresh({topic:'product',symbol});
     if(['queued','running'].includes(job.state))deadlines.set(symbol,Date.now()+150000);
     value=await read(symbol);draw(panel,value,job.cached?'已复用缓存':'');
    }
   }
   if(['queued','running'].includes(value.job?.state)){
    if(!deadlines.has(symbol))deadlines.set(symbol,Date.now()+150000);
    if(Date.now()>deadlines.get(symbol)){draw(panel,value,'本轮等待已超时，可稍后点击更新分析');panel.querySelector('.analysis-refresh').disabled=false}
   }else deadlines.delete(symbol);
  }catch(error){
   panel.querySelector('.analysis-state').textContent=error.message||'产品分析暂不可用';panel.querySelector('.analysis-refresh').disabled=!localMode;
  }finally{panel.dataset.busy='false'}
 }
 function select(root,tab,generate=true){
  if(!root)return;const panel=root.querySelector('[data-analysis-panel]'),analysis=tab==='analysis';
  root.querySelector('[data-detail-chart]').hidden=analysis;panel.hidden=!analysis;
  for(const button of root.querySelectorAll('[data-detail-tab]')){const on=button.dataset.detailTab===tab;button.classList.toggle('on',on);button.setAttribute('aria-pressed',String(on))}
  if(analysis)load(panel,generate);
  else{
   const symbol=root.dataset.productDetail,i=root.dataset.detailId,p=i==='market'?MarketDashboard.currentProduct(symbol):s?.positions.find(v=>v.key===symbol);
   if(p)activateDetail(p,i);
  }
 }
 document.addEventListener('click',event=>{
  const tab=event.target.closest('[data-detail-tab]');if(tab){select(tab.closest('[data-product-detail]'),tab.dataset.detailTab);return}
  const refresh=event.target.closest('.analysis-refresh');if(refresh)load(refresh.closest('[data-analysis-panel]'),true,true);
 });
 setInterval(()=>{if(!document.hidden)for(const panel of document.querySelectorAll('[data-analysis-panel]'))if(active(panel)&&(!deadlines.has(panel.dataset.analysisPanel)||Date.now()<=deadlines.get(panel.dataset.analysisPanel)))load(panel)},5000);
 window.ProductAnalysis={select};
})();
