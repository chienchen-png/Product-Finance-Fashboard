/* 人工事实录入：预览与提交。浏览器不计算或猜测成交。 */
(()=>{
 let preview=null;
 const dialog=$('import-dialog'),form=$('import-form'),message=$('import-message');
 const samples={
  trades:{kind:'trades',rows:[{id:'手机成交编号',time:null,trade_date:null,code:'510300',exchange:'SH',name:'沪深300ETF',side:'buy',quantity:100,price:null,fee:null}]},
  pending:{kind:'pending',rows:[]},
  snapshot:{kind:'snapshot',snapshot:{id:'手机快照编号',reported_at:null,summary:{total_assets:'',market_value:'',available_cash:'',daily_profit:'',unrealized_profit:''},positions:[{code:'510300',exchange:'SH',name:'沪深300ETF',quantity:100,average_cost:'',price:''}]}},
  watchlist:{kind:'watchlist',rows:[{symbol:'SH:510300',name:'沪深300ETF',product_type:'etf'}]}
 };
 const invalidate=()=>{preview=null;$('import-commit').disabled=true};
 const beijingNow=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date()).replace(' ','T');
 function layout(){
  const kind=$('import-kind').value,manual=$('import-mode').value==='manual';
  $('trade-fields').hidden=!(kind==='trades'&&manual);
  $('snapshot-fields').hidden=!(kind==='snapshot'&&manual);
  $('file-fields').hidden=manual&&(kind==='trades'||kind==='snapshot');
  if(kind==='snapshot'&&!form.elements.snapshot_time.value)form.elements.snapshot_time.value=beijingNow();
  invalidate();message.textContent=kind==='snapshot'?'首次填手机汇总与全部持仓开账；有冻结时填现金余额，无法确认现金则先撤单再对账':'成交以手机确认为准；编号留空按内容去重，相同时间的独立成交请填手机编号';
 }
 function addPosition(){
  const row=document.createElement('tr');
  row.innerHTML='<td><input data-field="code" inputmode="numeric" maxlength="6" aria-label="持仓代码"><small class="snapshot-name"></small></td><td><select data-field="exchange" aria-label="持仓交易所"><option>SH</option><option>SZ</option><option>BJ</option></select></td><td><input data-field="quantity" type="number" min="1" step="1" aria-label="持仓数量"></td><td><input data-field="average_cost" inputmode="decimal" aria-label="持仓均价"></td><td><input data-field="price" inputmode="decimal" aria-label="手机现价"></td><td><input data-field="available_quantity" type="number" min="0" step="1" aria-label="可卖数量"></td><td><button type="button" aria-label="删除此持仓">删除</button></td>';
  row.querySelector('button').onclick=()=>{row.remove();invalidate()};
  row.querySelector('[data-field="code"]').onchange=async e=>{
   const code=e.target.value.trim(),exchange=交易所前缀(code);if(!/^\d{6}$/.test(code)||!exchange)return;
   row.querySelector('[data-field="exchange"]').value=exchange;
   row.dataset.productName='';row.querySelector('small').textContent='';
   try{const r=await fetch('/api/lookup?symbol='+exchange+':'+code,{headers:{'X-Dashboard-Token':localToken}});if(!r.ok)return;const v=await r.json();if(e.target.value.trim()!==code)return;row.dataset.productName=v.name||code;row.querySelector('small').textContent=v.name||code}catch{}
  };
  $('snapshot-rows').append(row);invalidate();
 }
 $('snapshot-add').onclick=addPosition;
 async function post(route,payload){const response=await fetch(route,{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':localToken},body:JSON.stringify(payload)});const value=await response.json();if(!response.ok)throw Error((value.errors||[value.error||'请求失败']).join('；'));return value}
 function payload(){
  const kind=$('import-kind').value;
  if(kind==='trades'&&$('import-mode').value==='manual'){
   const values=Object.fromEntries(new FormData(form)),when=values.trade_time||null;
   return {kind,rows:[{id:values.trade_id||null,code:values.code,exchange:values.exchange,name:values.name||values.code,side:values.side,quantity:Number(values.quantity),price:values.trade_price||null,fee:values.fee||null,time:when,trade_date:when?when.slice(0,10):null}]};
  }
  if(kind==='snapshot'&&$('import-mode').value==='manual'){
   const values=form.elements,positions=[...$('snapshot-rows').rows].map(row=>{
    const get=key=>row.querySelector('[data-field="'+key+'"]').value.trim(),code=get('code');
    if(!/^\d{6}$/.test(code))throw Error('请填写每只持仓的6位代码，或删除空行');
    const p={code,exchange:get('exchange'),name:row.dataset.productName||code,quantity:Number(get('quantity')),average_cost:get('average_cost'),price:get('price')};
    if(get('available_quantity')!=='')p.available_quantity=Number(get('available_quantity'));return p;
   });
   return {kind,snapshot:{id:'手机-'+crypto.randomUUID(),reported_at:values.snapshot_time.value||null,summary:{total_assets:values.snapshot_total.value,available_cash:values.snapshot_cash.value,market_value:values.snapshot_market.value,daily_profit:values.snapshot_daily.value||null,unrealized_profit:values.snapshot_profit.value||null},positions}};
  }
  const text=$('import-text').value.trim();if(!text)throw Error('请填写或选择文件');
  if(text.startsWith('{')||text.startsWith('[')){const parsed=JSON.parse(text);return Array.isArray(parsed)?{kind,rows:parsed}:{...parsed,kind}}
  return {kind,csv:text};
 }
 $('import-open').onclick=()=>{if(!localMode){alert('记录请打开本机服务');return}dialog.showModal();layout()};
 $('import-close').onclick=()=>dialog.close();
 $('import-kind').onchange=layout;$('import-mode').onchange=layout;
 $('import-sample').onclick=()=>{$('import-text').value=JSON.stringify(samples[$('import-kind').value],null,2);preview=null;$('import-commit').disabled=true};
 $('import-file').onchange=async e=>{const f=e.target.files[0];if(!f)return;if(f.size>1024*1024){message.textContent='文件限1MiB';return}$('import-text').value=await f.text();preview=null;$('import-commit').disabled=true};
 // 最小写入：6位代码定交易所、接口带出名称；成交价、数量、时间只有用户知道，必须本人填。
 const 交易所前缀=code=>/^[56]/.test(code)?'SH':/^[013]/.test(code)?'SZ':/^[489]/.test(code)?'BJ':null;
 let 查询序号=0;
 async function 补全产品(){
  if(!localMode||$('import-kind').value!=='trades'||$('import-mode').value!=='manual')return;
  const 字段=form.elements;
  const code=String(字段.code.value||'').replace(/[０-９]/g,d=>String.fromCharCode(d.charCodeAt(0)-0xFEE0)).replace(/\D/g,'');
  if(code.length!==6)return;
  const 交易所=交易所前缀(code);if(交易所)字段.exchange.value=交易所;
  const 本序号=++查询序号;
  try{
   const r=await fetch('/api/lookup?symbol='+交易所+':'+code,{headers:{'X-Dashboard-Token':localToken}});
   if(本序号!==查询序号||字段.code.value!==code)return;
   if(!r.ok){message.textContent=交易所+' '+code+' 未取到行情，请核对代码与交易所';return}
   const v=await r.json();
   if(v.name&&(!字段.name.value||字段.name.dataset.autoCode)){字段.name.value=v.name;字段.name.dataset.autoCode=code}
   message.textContent=(v.name||code)+' 最新 '+v.price+'（'+(v.source_as_of||'时间待核')+'）；成交价请按手机实际填写';
  }catch(error){if(本序号===查询序号)message.textContent='行情暂不可用，可直接填写代码与名称'}
 }
 form.elements.code.addEventListener('blur',补全产品);
 form.elements.code.addEventListener('change',补全产品);
 form.elements.code.addEventListener('input',()=>{查询序号++;if(form.elements.name.dataset.autoCode){form.elements.name.value='';delete form.elements.name.dataset.autoCode}});
 form.elements.name.addEventListener('input',()=>delete form.elements.name.dataset.autoCode);
 form.addEventListener('input',invalidate);
 form.addEventListener('change',invalidate);
 form.onsubmit=async e=>{e.preventDefault();try{preview=await post('/api/import/preview',payload());message.textContent=preview.changes.length?preview.changes.map(c=>c.action+(c.id?' '+c.id:'')+(c.quantity?' · '+c.quantity+'份':'')+(c.price?' · '+c.price+'元':'')+(c.quantity&&c.fee==null?' · 费用待核':'')+(c.count!=null?' · '+c.count+'项':'')+(c.checks?' · 市值差 '+c.checks.market_value_difference+'元':'')).join('\n'):'无新增记录';$('import-commit').disabled=false}catch(error){message.textContent=error.message;preview=null;$('import-commit').disabled=true}};
 $('import-commit').onclick=async()=>{if(!preview)return;const b=$('import-commit');b.disabled=true;try{const result=await post('/api/import/commit',{token:preview.token,expected_revision:preview.revision});message.textContent='已保存 · '+result.changes.length+'项变更';preview=null;await fetchView();window.MarketDashboard?.update()}catch(error){message.textContent=error.message;preview=null}};
})();
