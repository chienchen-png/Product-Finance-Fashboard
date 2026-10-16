"""低频华泰研究资料：独立后台采集，共享市场缓存，不写账户或生成交易决定。"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import threading
import time
import requests
import 账户核心 as core
from 数据契约 import dataset
from 数据源 import 华泰 as ht

_lock=threading.Lock()
_jobs={}
TOOLS={
    'indicators':('queryIndicator','mx_1779108020995'),
    'flows':('queryIndicator','mx_1779108020995'),
    'events':('marketInsight','mx_1779096185749')}
LABELS={'indicators':'技术指标与产品资金','flows':'行业资金观察','events':'市场事件与资讯'}


def queries(path):
    holdings=core.calculate(core.load_account(path))['positions']
    products='、'.join(p['name']+'('+p['code']+')' for p in holdings[:8])
    products=products or '沪深300ETF华泰柏瑞510300'
    return {
        'indicators':f'查询{products}的MA5、MA20、MA60、MACD、KDJ、RSI、今日及近3日和近5日主力净流入，注明日期、单位和口径。缺失明确留空。',
        'flows':'查询最新A股行业主力资金净流入前5名，返回行业名称、主力净流入金额、涨跌幅、行情日期、数据来源和资金流定义。',
        'events':f'整理最近24小时影响{products}的新闻、政策和事件，列出原始来源、发布时间和可核验链接，区分事实与观点，不提供买卖建议。'}


def fetch(kind,query):
    tool,skill=TOOLS[kind]
    secret=ht.key()
    if not secret:raise ValueError('未配置华泰密钥')
    response=requests.post('https://ai.zhangle.com/edge/entry/gate/api/finAnalysis/'+tool,
        json={'query':query},headers={'apiKey':secret,'skillCode':skill,'Content-Type':'application/json'},
        timeout=65,allow_redirects=False)
    if response.status_code!=200:raise ValueError(f'华泰HTTP {response.status_code}')
    value=response.json()
    if value.get('code')!=0:raise ValueError('华泰本轮未返回可用资料')
    text=(value.get('data') or {}).get('answer')
    if not isinstance(text,str) or not text.strip():raise ValueError('华泰未返回文本资料')
    text=text[:100000]
    return dict(id=kind,title=LABELS[kind],query=query,answer=text,retrieved_at=core.now(),
        source='华泰Skill '+tool,source_as_of=None,verification='supplier_ai_unverified',
        content_hash=hashlib.sha256(text.encode()).hexdigest())


def run(path):
    import 市场同步 as market
    previous=market.read_section(path,'huatai');rows={r['id']:r for r in previous.get('data',[])}
    errors=[]
    for kind,query in queries(path).items():
        try:rows[kind]=fetch(kind,query)
        except Exception:errors.append({'kind':kind,'reason':'本轮华泰资料获取失败，未以空值覆盖旧资料'})
        value=dataset('huatai',list(rows.values()),'华泰Skill',status='partial',
            reason='供应商AI生成资料，数值、事件及日期待独立核验；不替代结构化行情',
            configured=True,pending=True,errors=errors)
        market._store_section(path,'huatai',value)
    value=dataset('huatai',list(rows.values()),'华泰Skill',status='partial' if errors else 'unknown',
        reason='供应商AI生成资料，数值、事件及日期待独立核验；不替代结构化行情',
        configured=True,pending=False,errors=errors)
    market._store_section(path,'huatai',value)
    return value


def request(path):
    """由用户立即更新触发；一分钟去重，后台资料不阻塞报价/K线。"""
    if not ht.configured():return False
    path=Path(path);key=str(path.resolve())
    with _lock:
        state=_jobs.setdefault(key,{'busy':False,'last':-1000})
        if state['busy'] or time.monotonic()-state['last']<60:return False
        state.update(busy=True,last=time.monotonic())
    def worker():
        try:run(path)
        finally:
            with _lock:state['busy']=False
    threading.Thread(target=worker,name='华泰研究资料',daemon=True).start()
    return True
