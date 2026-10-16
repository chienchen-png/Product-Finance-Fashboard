"""独立投研缓存与有限后台任务；外部请求不持文件锁。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid
import 账户核心 as core
from 数据契约 import dataset,revision,validate_symbol,TZ

TOPICS={'market_a':'A股市场','overseas':'海外市场','capital':'资金观察','events':'事件与政策','product':'产品分析','sector':'行业专题','fund':'产品资金快照'}
_lock=threading.RLock()
_engines={}
_access={}


def file_for(path):return Path(path).parent.parent/'投研缓存.json'
def empty():return dict(schema_version=1,documents={},jobs={})
def load(path):
    try:return core.read_json(file_for(path),empty())
    except ValueError:return empty()


def mutate(path,fn):
    target=file_for(path)
    with _lock,core.lock(target):
        data=load(path);fn(data)
        # 最新内容有界，优先保留当前持仓资料。
        held={p['key'] for p in core.calculate(core.load_account(path))['positions']}
        docs=data['documents']
        if len(docs)>20:
            ranked=sorted(docs,key=lambda k:(docs[k].get('subject',{}).get('symbol') in held,_access.get((str(Path(path).resolve()),k),docs[k].get('retrieved_at',''))),reverse=True)
            for key in ranked[20:]:docs.pop(key,None)
        jobs=data['jobs'];finished=[k for k in jobs if jobs[k]['state'] not in ('queued','running')]
        for key in sorted(finished,key=lambda k:jobs[k].get('finished_at',''))[:-20]:jobs.pop(key,None)
        core.write_json(target,data)


def migrate(path):
    target=file_for(path)
    if target.exists():return
    market=Path(path).parent.parent/'市场缓存.json'
    with _lock,core.lock(market):
        raw=core.read_json(market,{'sections':{}});old=raw.get('sections',{}).get('huatai',{})
        new=empty()
        for row in old.get('data',[]):
            key='legacy:'+row['id'];new['documents'][key]=dict(row,key=key,topic='legacy',subject={},reported_as_of=row.get('source_as_of'))
        core.write_json(target,new)
        check=load(path)
        assert all(check['documents'][k]['answer']==v['answer'] and check['documents'][k].get('content_hash')==v.get('content_hash') for k,v in new['documents'].items())
        if 'huatai' in raw.get('sections',{}):
            raw['sections'].pop('huatai');core.write_json(market,raw)


def legacy(path):
    data=load(path)
    # 未启动服务的历史工具也可读取旧分区，读请求本身不迁移文件。
    if not file_for(path).exists():
        raw=core.read_json(Path(path).parent.parent/'市场缓存.json',{'sections':{}})
        return raw.get('sections',{}).get('huatai',dataset('huatai',[],'华泰Skill',status='unavailable'))
    docs=list(data['documents'].values());jobs=list(data['jobs'].values())
    return dataset('huatai',docs,'华泰Skill',status='unknown' if docs else 'unavailable',
        retrieved_at=max((r.get('retrieved_at','') for r in docs),default=core.now()),
        configured=configured(),pending=any(r['state'] in ('queued','running') for r in jobs),errors=[j for j in jobs if j['state']=='failed'])


def recover(path):
    data=load(path)
    if any(j['state'] in ('queued','running') for j in data['jobs'].values()):
        def reset(value):
            for j in value['jobs'].values():
                if j['state'] in ('queued','running'):j.update(state='failed',finished_at=core.now(),error='上次运行已结束，请重新更新')
        mutate(path,reset)


def configured():
    from 数据源 import 华泰
    return 华泰.configured()


def funds(path):
    docs=load(path)['documents'].values();data=[]
    for doc in docs:
        if doc.get('topic')=='fund' and doc.get('structured_data'):
            data.append(dict(doc['structured_data'],name=doc['subject'].get('name'),retrieved_at=doc['retrieved_at'],content_hash=doc['content_hash']))
    return dataset('fund_flows',data,'华泰Skill queryIndicator',status='unknown' if data else 'unavailable',reason='供应商报告值；行情时刻未核验，非ETF申赎资金',retrieved_at=max((r['retrieved_at'] for r in data),default=core.now()))


def trading_date():
    from 看板服务 import is_trading_day
    now=datetime.now(TZ);day=now.date()
    if now.hour<9 or (now.hour==9 and now.minute<30):day-=timedelta(days=1)
    for _ in range(30):
        if is_trading_day(day) is True:return day.isoformat()
        day-=timedelta(days=1)
    raise ValueError('交易日历未覆盖')


def spec(path,topic,symbol=None,sector=None):
    if topic not in TOPICS:raise ValueError('不支持的分析主题')
    day=trading_date();subject={};provider_kind=topic
    if topic in ('product','fund'):
        validate_symbol(symbol)
        import 市场同步 as market
        products={r['symbol']:r for r in market.tracked_products(path)}
        names={k:r.get('name',k) for k,r in products.items()}
        if not symbol.startswith(('SH:','SZ:','BJ:')) and (topic=='fund' or symbol not in products):raise ValueError('该产品暂无已接入的分析接口')
        if topic=='product' and (not symbol.startswith(('SH:','SZ:','BJ:')) or products.get(symbol,{}).get('product_type')=='index'):provider_kind='product_market'
        subject=dict(symbol=symbol,name=names.get(symbol,symbol));object_name=subject['name']+'('+symbol+')'
    elif topic=='sector':
        import 市场同步 as market
        rows=market.read_section(path,'sectors:industry')['data'];item=next((r for r in rows if r['id']==sector),None)
        if not item:raise ValueError('请选择当前缓存中的行业')
        subject=dict(sector=sector,name=item['name'],classification='新浪行业');object_name=item['name']+'（入口来自新浪行业分类；报告须说明实际采用分类，禁止混同）'
    else:object_name=''
    queries={
        'market_a':f'分析截至{day}最近交易日A股的量价、行业强弱、市场趋势与关键驱动，给出正反情景，注明资料日期和原始来源，区分事实与观点，不提供候选股票或交易指令。',
        'overseas':f'分析截至北京时间{day}最近已收盘的港股和美股市场趋势、利率汇率影响及关键事件，逐市场注明交易日期与原始来源，区分事实与观点，不提供候选股票或交易指令。',
        'capital':f'分析截至{day}A股行业主力资金近期动向，说明统计分类、主力定义、日期、来源及不确定性，区分事实与观点，不提供候选股票或交易指令。',
        'events':f'整理截至{day}最近48小时影响A股、纳斯达克资产和黄金的重要政策与事件，注明发布时间和原始来源链接，说明影响路径及相反情景，不提供候选股票或交易指令。',
        'product':f'截至{day}，对{object_name}进行综合分析诊断，重点说明趋势、资金、关键事件、估值与风险，注明每项数据日期和原始来源，不提供候选股票或交易指令。',
        'sector':f'分析{object_name}的趋势、景气、资金、催化和关键风险，注明每项数据日期、样本分类和原始来源，不提供候选股票或交易指令。',
        'fund':f'查询{object_name}在{day}的当日主力净流入，以JSON对象返回code、date、net_inflow_yuan、definition、source_url；金额单位为人民币元，缺失字段为null，不提供额外分析。'}
    key=topic+':'+(symbol or sector or 'market')
    return dict(key=key,topic=topic,provider_kind=provider_kind,subject=subject,title=TOPICS[topic]+(' · '+subject['name'] if subject else ''),query_version=2,query=queries[topic],requested_as_of=day)


class Engine:
    def __init__(self,path,fetcher=None,clock=time.monotonic,ttl=1800,budget=120):
        self.path=Path(path);self.clock=clock;self.ttl=ttl;self.budget=budget;self.fetcher=fetcher
        self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='华泰资料');self.lock=threading.RLock();self.active={}
    def submit(self,topic,symbol=None,sector=None):
        if not configured() and self.fetcher is None:raise ValueError('未配置华泰密钥')
        definition=spec(self.path,topic,symbol,sector);key=definition['key']
        with self.lock:
            if key in self.active:return dict(self.active[key],reused=True)
            doc=load(self.path)['documents'].get(key)
            if doc and doc.get('query_version')==definition['query_version'] and doc.get('requested_as_of')==definition['requested_as_of']:
                try:age=(datetime.now(TZ)-datetime.fromisoformat(doc['retrieved_at'])).total_seconds()
                except (ValueError,KeyError):age=self.ttl+1
                if 0<=age<self.ttl:return dict(state='succeeded',key=key,cached=True)
            if len(self.active)>=6:raise ValueError('分析队列已满，请稍后更新')
            job=dict(job_id=uuid.uuid4().hex,key=key,state='queued',started_at=None,finished_at=None,error=None)
            self.active[key]=job
            mutate(self.path,lambda d:d['jobs'].update({key:dict(job)}))
            self.pool.submit(self._run,definition,job)
            return dict(job)
    def _run(self,definition,job):
        key=definition['key'];started=self.clock()
        try:
            job.update(state='running',started_at=core.now());mutate(self.path,lambda d:d['jobs'].update({key:dict(job)}))
            import 华泰资料 as provider
            row=(self.fetcher or provider.fetch)(definition['provider_kind'],definition['query'])
            if self.clock()-started>self.budget:raise TimeoutError('分析请求超过本轮时限')
            body=row.get('answer')
            if not isinstance(body,str) or not body.strip():raise ValueError('未返回可用报告正文')
            try:parsed=provider.parse_fund_answer(body,definition['subject']['symbol'],definition['requested_as_of']) if definition['topic']=='fund' else None
            except (ValueError,TypeError):raise ValueError('资金JSON解析或代码、日期、单位校验失败') from None
            doc=dict(row,**definition,reported_as_of=None,structured_data=parsed,verification='supplier_ai_unverified')
            # 不将供应商自称的数据日当作独立确认；资金JSON保留自身日期字段。
            doc['answer']=body[:100000];doc['truncated']=len(body)>100000
            doc['content_hash']=hashlib.sha256(doc['answer'].encode()).hexdigest()
            def commit(data):data['documents'][key]=doc
            mutate(self.path,commit);job.update(state='succeeded')
        except Exception as exc:
            if isinstance(exc,(ValueError,TimeoutError)):reason=str(exc)[:160]
            elif isinstance(exc,OSError):reason='接口连接失败'
            else:reason='分析资料获取失败'
            job.update(state='failed',error=reason)
        finally:
            job['finished_at']=core.now()
            mutate(self.path,lambda data:data['jobs'].update({key:dict(job)}))
            with self.lock:self.active.pop(key,None)


def engine(path):
    key=str(Path(path).resolve())
    with _lock:
        if key not in _engines:_engines[key]=Engine(path)
        return _engines[key]


def view(path,topic=None,symbol=None,sector=None):
    if topic is not None and topic not in TOPICS and topic!='legacy':raise ValueError('不支持的分析主题')
    data=load(path);docs=data['documents']
    if topic:
        key=topic+':'+(symbol or sector or 'market')
        # 迁移的旧资料可通过其key读取，不重新命名成新诊断。
        if topic=='legacy':key='legacy:'+str(symbol)
        if key not in docs:return dict(document=None,job=data['jobs'].get(key),configured=configured())
        _access[(str(Path(path).resolve()),key)]=core.now()
        return dict(document=docs[key],job=data['jobs'].get(key),configured=configured())
    meta=[{k:v for k,v in doc.items() if k not in ('answer','structured_data','query')} for doc in docs.values()]
    return dict(documents=sorted(meta,key=lambda r:r.get('retrieved_at',''),reverse=True),jobs=list(data['jobs'].values()),configured=configured())
