"""低频华泰研究资料：独立后台采集与报告缓存，不写账户或生成交易决定。"""
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


def parse_fund_answer(answer,symbol,expected_day):
    """只接受完整JSON对象；可解析仍是供应商报告值。"""
    import re
    from datetime import date
    from 数据契约 import decimal_text,validate_symbol
    validate_symbol(symbol)
    value=str(answer).strip()
    match=re.fullmatch(r'```(?:json)?\s*(.*?)\s*```',value,re.S)
    data=json.loads(match.group(1) if match else value)
    if not isinstance(data,dict) or data.get('code')!=symbol.split(':')[1]:raise ValueError('资金证券代码不符')
    stamp=data.get('date')
    if not isinstance(stamp,str) or date.fromisoformat(stamp).isoformat()!=stamp or stamp!=expected_day:raise ValueError('资金数据日期不符')
    if data.get('unit') not in (None,'CNY','元','人民币元'):raise ValueError('资金金额单位不符')
    raw=data.get('net_inflow_yuan')
    if raw is None or isinstance(raw,bool):raise ValueError('缺少有效资金金额')
    number=decimal_text(raw)
    if number is None:raise ValueError('缺少有效资金金额')
    definition=data.get('definition')
    if not isinstance(definition,str) or not definition.strip():raise ValueError('资金口径缺失')
    return dict(symbol=symbol,date=stamp,net_inflow_yuan=number,unit='CNY',definition=definition[:1000],source_url=data.get('source_url') if isinstance(data.get('source_url'),str) and data['source_url'].startswith(('https://','http://')) else None,verification='supplier_ai_unverified')

_lock=threading.Lock()
_jobs={}
TOOLS={
    'indicators':('queryIndicator','mx_1779108020995'),
    'flows':('queryIndicator','mx_1779108020995'),
    'events':('marketInsight','mx_1779096185749'),
    **{k:('marketInsight','mx_1779096185749') for k in ('market_a','overseas','capital','sector','product_market')},
    'product':('diagnosisStock','mx_1779096185749'),
    'fund':('queryIndicator','mx_1779108020995')}
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
    budget=60 if tool=='queryIndicator' else 120
    deadline=time.monotonic()+budget
    try:
        with requests.post('https://ai.zhangle.com/edge/entry/gate/api/finAnalysis/'+tool,
            json={'query':query},headers={'apiKey':secret,'skillCode':skill,'Content-Type':'application/json'},
            timeout=(5,budget-5),allow_redirects=False,stream=True) as response:
            if response.status_code!=200:raise ValueError('接口权限受限' if response.status_code in (401,403) else '接口限流' if response.status_code==429 else f'华泰HTTP {response.status_code}')
            timer=threading.Timer(max(.01,deadline-time.monotonic()),response.close);timer.daemon=True;timer.start()
            try:
                chunks=[];size=0
                for chunk in response.iter_content(8192):
                    if time.monotonic()>deadline:raise TimeoutError('分析请求超过本轮时限')
                    size+=len(chunk)
                    if size>1024*1024:raise ValueError('报告响应超过1MiB')
                    chunks.append(chunk)
                value=json.loads(b''.join(chunks))
            finally:timer.cancel()
    except requests.Timeout as exc:raise TimeoutError('华泰接口超时') from exc
    except requests.ConnectionError as exc:raise OSError('华泰接口连接失败') from exc
    if value.get('code')!=0:raise ValueError('华泰本轮未返回可用资料')
    text=(value.get('data') or {}).get('answer')
    if not isinstance(text,str) or not text.strip():raise ValueError('华泰未返回文本资料')
    if kind=='fund' and len(text)>100000:raise ValueError('资金JSON超长')
    return dict(id=kind,title=LABELS.get(kind,kind),query=query,answer=text,retrieved_at=core.now(),
        source='华泰Skill '+tool,source_as_of=None,verification='supplier_ai_unverified',
        content_hash=hashlib.sha256(text.encode()).hexdigest())


def run(path):
    """兼容旧工具的显式三类查询；新网页仅更新用户选择的主题。"""
    import 投研缓存 as store
    store.migrate(path);errors=[]
    for kind,query in queries(path).items():
        try:
            row=fetch(kind,query);row.update(key='legacy:'+kind,topic='legacy',subject={})
            store.mutate(path,lambda data:data['documents'].update({'legacy:'+kind:row}))
        except Exception:errors.append({'kind':kind,'reason':'本轮获取失败，沿用旧资料'})
    value=store.legacy(path);value.update(errors=errors,pending=False,status='partial' if errors else 'unknown');return value


def request(path,topic='market_a',symbol=None,sector=None):
    import 投研缓存 as store
    return store.engine(path).submit(topic,symbol,sector)


def funds(path):
    import 投研缓存 as store
    return store.funds(path)
