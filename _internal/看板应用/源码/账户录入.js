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
  const trade=kind==='trades'&&manual,pending=kind==='pending'&&manual;
  $('trade-fields').hidden=!trade;
  $('pending-fields').hidden=!pending;
  $('snapshot-fields').hidden=!(kind==='snapshot'&&manual);
  $('file-fields').hidden=manual&&kind!=='watchlist';
  // 时间默认现在；补记历史成交时在“更多”里改。
  if(trade&&!form.elements.trade_time.value)form.elements.trade_time.value=beijingNow();
  if(pending&&!$('pending-time').value)$('pending-time').value=beijingNow();
  if(kind==='snapshot'&&!form.elements.snapshot_time.value)form.elements.snapshot_time.value=beijingNow();
  // 必填只作用于当前显示的录入块，隐藏块的必填不能阻塞提交。
  [[$('trade-fields'),trade,['code','quantity','trade_price']],[$('pending-fields'),pending,['pending-code','pending-quantity','pending-price']]]
   .forEach(([块,显示,字段名])=>块.querySelectorAll('input,select').forEach(元素=>{元素.required=显示&&字段名.includes(元素.name||元素.id)}));
  invalidate();message.textContent=kind==='snapshot'?'首次填手机汇总与全部持仓开账；有冻结时填现金余额，无法确认现金则先撤单再对账':pending?'委托以手机提交为准；编号与提交时间自动生成':'成交以手机确认为准；编号留空按内容去重，相同时间的独立成交请填手机编号';
  载入费率().then(提示);
 }
 function addPosition(){
  const row=document.createElement('tr');
  row.innerHTML='<td><input data-field="code" inputmode="numeric" maxlength="6" aria-label="持仓代码"><small class="snapshot-name"></small></td><td><select data-field="exchange" aria-label="持仓交易所"><option>SH</option><option>SZ</option><option>BJ</option><option>HK</option></select></td><td><input data-field="quantity" type="number" min="1" step="1" aria-label="持仓数量"></td><td><input data-field="average_cost" inputmode="decimal" aria-label="持仓均价"></td><td><input data-field="price" inputmode="decimal" aria-label="手机现价"></td><td><input data-field="available_quantity" type="number" min="0" step="1" aria-label="可卖数量"></td><td><button type="button" aria-label="删除此持仓">删除</button></td>';
  row.querySelector('button').onclick=()=>{row.remove();invalidate()};
  row.querySelector('[data-field="code"]').onchange=async e=>{
   const code=e.target.value.trim(),exchange=交易所前缀(code);if(!/^\d{5,6}$/.test(code)||!exchange)return;
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
   return {kind,rows:[{id:values.trade_id||null,code:values.code,exchange:values.exchange,name:values.name||values.code,side:values.side,quantity:Number(values.quantity),price:values.trade_price||null,fee:values.fee||null,fx:values.hk_fx||null,time:when,trade_date:when?when.slice(0,10):null}]};
  }
  if(kind==='pending'&&$('import-mode').value==='manual'){
   const when=$('pending-time').value||null,code=$('pending-code').value.trim();
   return {kind,append:true,rows:[{id:$('pending-id').value||null,time:when,code,exchange:null,name:$('pending-name').value||code,side:$('pending-side').value,quantity:Number($('pending-quantity').value),price:$('pending-price').value||null,fx:$('pending-fx').value||null,status:$('pending-status').value}]};
  }
  if(kind==='snapshot'&&$('import-mode').value==='manual'){
   const values=form.elements,positions=[...$('snapshot-rows').rows].map(row=>{
    const get=key=>row.querySelector('[data-field="'+key+'"]').value.trim(),code=get('code');
    if(!/^\d{6}$/.test(code))throw Error('请填写每只持仓的6位代码，或删除空行');
    const p={code,exchange:get('exchange'),name:row.dataset.productName||code,quantity:Number(get('quantity')),average_cost:get('average_cost'),price:get('price')};
    if(get('available_quantity')!=='')p.available_quantity=Number(get('available_quantity'));return p;
   });
   return {kind,snapshot:{id:'手机-'+crypto.randomUUID(),reported_at:values.snapshot_time.value||null,fx:values.snapshot_fx.value||null,summary:{total_assets:values.snapshot_total.value,available_cash:values.snapshot_cash.value,market_value:values.snapshot_market.value,daily_profit:values.snapshot_daily.value||null,unrealized_profit:values.snapshot_profit.value||null},positions}};
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
 // 最小写入：5位港股或6位沪深北代码定交易所、接口带出名称、费用与折算率；成交价和数量只有用户知道。
 const 交易所前缀=code=>/^\d{5}$/.test(code)?'HK':/^[56]/.test(code)?'SH':/^[013]/.test(code)?'SZ':/^[489]/.test(code)?'BJ':null;
 const 行情说明={trade:'',pending:''},查询序号={trade:0,pending:0};
 let feeRules=null;
 // 表单只做预估展示；实际入账费用由服务端按同一费率推定。
 async function 载入费率(){if(feeRules||!localMode)return;try{const r=await fetch('/api/fees',{headers:{'X-Dashboard-Token':localToken}});if(r.ok)feeRules=(await r.json()).rules||{}}catch{}}
 function 估费(交易所,数量,价格){const rule=feeRules&&feeRules[交易所],q=Number(数量),p=Number(价格);if(!rule||!(q>0)||!(p>0))return null;return {text:(Math.round(p*q*Number(rule.rate)*100)/100).toFixed(2),label:rule.label,单位:交易所==='HK'?'港元':'元'}}
 function 提示成交(){
  const f=form.elements,交易所=交易所前缀(String(f.code.value||'').trim()),费=交易所?估费(交易所,f.quantity.value,f.trade_price.value):null;
  const 费率=(feeRules&&feeRules[交易所]&&feeRules[交易所].label)||'赛事规则';
  const 换算=交易所==='HK'&&f.hk_fx.value?' · 折算率 '+f.hk_fx.value:'';
  $('trade-hint').textContent=(行情说明.trade?行情说明.trade+' · ':'')+(交易所?'自动补齐：'+交易所+' · '+(f.name.value||'名称待带出')+(费?' · 费用约 '+费.text+' '+费.单位+'（'+费.label+'）':' · 费用按'+费率+'自动计算')+换算:'输入5位港股或6位沪深北代码后识别交易所、名称与费用');
 }
 function 提示委托(){
  const 交易所=交易所前缀(String($('pending-code').value||'').trim());
  const 换算=交易所==='HK'&&$('pending-fx').value?' · 折算率 '+$('pending-fx').value:'';
  $('pending-hint').textContent=(行情说明.pending?行情说明.pending+' · ':'')+(交易所?'自动补齐：'+交易所+' · '+($('pending-name').value||'名称待带出')+' · 编号与提交时间自动生成'+换算:'输入5位港股或6位沪深北代码后识别交易所与名称');
 }
 function 提示(){const kind=$('import-kind').value;if(kind==='trades')提示成交();else if(kind==='pending')提示委托()}
 async function 补全汇率(目标){
  const 字段=目标==='trade'?form.elements.hk_fx:$('pending-fx');
  if(!字段||字段.dataset.manual)return;
  try{const r=await fetch('/api/lookup?symbol=FX:HKDCNY',{headers:{'X-Dashboard-Token':localToken}});if(!r.ok)return;const v=await r.json();
   if(v.price&&!字段.dataset.manual){字段.value=v.price;字段.dataset.auto='1'}}catch{}
 }
 async function 补全产品(目标){
  if(!localMode||$('import-mode').value!=='manual')return;
  const 成交=目标==='trade',代码=成交?form.elements.code:$('pending-code'),名称=成交?form.elements.name:$('pending-name');
  const code=String(代码.value||'').replace(/[０-９]/g,d=>String.fromCharCode(d.charCodeAt(0)-0xFEE0)).replace(/\D/g,'');
  if(code.length!==5&&code.length!==6)return;
  const 交易所=交易所前缀(code);if(成交&&交易所)form.elements.exchange.value=交易所;
  const 本序号=++查询序号[目标];
  if(!交易所){行情说明[目标]='无法按代码判断交易所';提示();return}
  if(交易所==='HK')await 补全汇率(目标);
  try{
   const r=await fetch('/api/lookup?symbol='+交易所+':'+code,{headers:{'X-Dashboard-Token':localToken}});
   if(本序号!==查询序号[目标]||String(代码.value||'').replace(/\D/g,'')!==code)return;
   if(!r.ok){行情说明[目标]=交易所+' '+code+' 未取到行情，请核对代码';提示();return}
   const v=await r.json();
   if(v.name&&(!名称.value||名称.dataset.autoCode)){名称.value=v.name;名称.dataset.autoCode=code}
   行情说明[目标]=(v.name||code)+' 现价 '+v.price+'（'+(v.source_as_of||'时间待核')+'）';
  }catch(error){if(本序号===查询序号[目标])行情说明[目标]='行情暂不可用'}
  提示();
 }
 for(const [目标,代码,名称] of [['trade',form.elements.code,form.elements.name],['pending',$('pending-code'),$('pending-name')]]){
  代码.addEventListener('blur',()=>补全产品(目标));
  代码.addEventListener('change',()=>补全产品(目标));
  代码.addEventListener('input',()=>{查询序号[目标]++;行情说明[目标]='';if(名称.dataset.autoCode){名称.value='';delete 名称.dataset.autoCode}});
  名称.addEventListener('input',()=>{delete 名称.dataset.autoCode;提示()});
 }
 // 用户手填折算率后不再被自动值覆盖。
 for(const 字段 of [form.elements.hk_fx,$('pending-fx')])字段.addEventListener('input',()=>{字段.dataset.manual='1';提示()});
 form.addEventListener('input',()=>{invalidate();提示()});
 form.addEventListener('change',()=>{invalidate();提示()});
 form.onsubmit=async e=>{e.preventDefault();try{preview=await post('/api/import/preview',payload());message.textContent=preview.changes.length?preview.changes.map(c=>c.action+(c.id?' '+c.id:'')+(c.quantity?' · '+c.quantity+'份':'')+(c.price?' · '+c.price+'元':'')+(c.fee!=null?' · 费用 '+c.fee+'元':'')+(c.quantity&&c.fee==null?' · 费用待核':'')+(c.count!=null?' · '+c.count+'项':'')+(c.time?' · 时间 '+c.time.replace('T',' ').replace('+08:00',''):'')+(c.checks?' · 市值差 '+c.checks.market_value_difference+'元':'')).join('\n'):'无新增记录';$('import-commit').disabled=false}catch(error){message.textContent=error.message;preview=null;$('import-commit').disabled=true}};
 $('import-commit').onclick=async()=>{if(!preview)return;const b=$('import-commit');b.disabled=true;try{const result=await post('/api/import/commit',{token:preview.token,expected_revision:preview.revision});message.textContent='已保存 · '+result.changes.length+'项变更';preview=null;await fetchView();window.MarketDashboard?.update()}catch(error){message.textContent=error.message;preview=null}};
})();
