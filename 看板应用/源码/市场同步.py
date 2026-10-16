"""共享市场采集与缓存；无账户查询、下单、AI推理。"""
import argparse
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from concurrent.futures import ThreadPoolExecutor
import 账户核心 as core
from 数据契约 import dataset, revision, freshness, merge_series, validate_symbol, TZ
from 数据源 import 公共行情 as public, 东方财富 as east
from 数据契约 import product_meta, normalize_cached_series
from zoneinfo import ZoneInfo

SECTIONS={'overview','ranks','sectors','flows','news','nav','announcements','huatai'}
_engines={}
_engine_lock=threading.Lock()
_cache_write_lock=threading.RLock()


def capabilities():
    """默认启用集；只列本机重复取数并核验过的能力，不从研究矩阵自动启用。"""
    return dict(sectors=['industry'],sector_main_net=False,flows=False,announcements=False,
        nav=True,kline_sources=['腾讯网页K线'],quote_sources=['华泰Skill getQuote','腾讯网页行情','新浪网页行情'],
        ranks=['stock','etf','lof'],news=True,huatai_research=True)


def account_path(data_root):
    p=Path(data_root)
    return p if p.suffix=='.json' else p/'账户记录/比赛账户.json'


def root_for(path):
    path=Path(path)
    return path.parent.parent if path.parent.name=='账户记录' else path.parent


def market_path(path):return root_for(path)/'市场缓存.json'
def watchlist_path(path):return root_for(path)/'本地自选.json'


def tracked_products(path):
    account=core.load_account(path)
    rows={p['key']:dict(symbol=p['key'],name=p['name'],product_type='holding')
          for p in core.calculate(account)['positions']}
    watch=core.read_json(watchlist_path(path), {'products':[]})
    for p in watch.get('products',[]):
        symbol=validate_symbol(p['symbol']);rows.setdefault(symbol,dict(p,symbol=symbol))
    for symbol,name,kind in public.BENCHMARKS:rows.setdefault(symbol,dict(symbol=symbol,name=name,product_type=kind))
    if len(rows)>50:raise ValueError('持仓、自选与基准合计超过50项')
    return list(rows.values())


def market_state(symbol=None, at=None):
    at=at or datetime.now(TZ)
    if symbol and not symbol.startswith(('SH:','SZ:','BJ:')):
        if symbol.startswith(('FX:','FUT:')):return 'unknown'
        meta=product_meta(symbol);local=at.astimezone(ZoneInfo(meta['timezone']))
        # 仅供调度的已知开闭市时钟；海外日历仍未验证，不代表可交易权限。
        return 'open' if local.weekday()<5 and (9,30)<=(local.hour,local.minute)<(meta['close_hour'],0) else 'closed'
    import 看板服务
    day=看板服务.is_trading_day(at.astimezone(TZ).date())
    if day is None:return 'unknown'
    if day and 看板服务.in_session(at):return 'open'
    return 'closed'


def session_key(symbol=None,at=None):
    at=at or datetime.now(TZ)
    meta=product_meta(symbol or 'SH:000001');local=at.astimezone(ZoneInfo(meta['timezone']))
    day=local.date()
    if (local.hour,local.minute)<(meta['close_hour'],0):day-=timedelta(days=1)
    import 看板服务
    for _ in range(30):
        valid=看板服务.is_trading_day(day) if meta['calendar_verified'] else day.weekday()<5
        if valid is None:return None
        if valid:return day.isoformat()
        day-=timedelta(days=1)
    return None


def unavailable(section, reason='尚未获取'):
    return dataset(section, [], None, status='unavailable', reason=reason)


def read_section(data_root, section):
    path=account_path(data_root)
    try:raw=core.read_json(market_path(path), {'sections':{}})
    except ValueError:return unavailable(section,'缓存损坏，等待后台重建')
    ds=raw.get('sections',{}).get(section)
    if not ds:return unavailable(section)
    result=dict(ds)
    state=market_state(None)
    if section=='overview':
        engine=collector(path)
        series=core.load_cache(path).get('series',{})
        data=[]
        for row in ds.get('data',[]):
            q=dict(row)
            q['status']=freshness(dict(status=ds['status'] if ds['status'] in ('stale','unavailable') else 'ok',source_as_of=q.get('source_as_of'),
                last_session=q.get('last_session') or session_key(q['symbol']),
                session_close_hour=product_meta(q['symbol'])['close_hour']), datetime.now(TZ),market_state(q['symbol']))
            access=engine.kline_state(q['symbol'],entry=series.get(q['symbol']))
            q['chart_available']=access['status'] not in ('unsupported','failed') and access.get('kind')!='permission'
            data.append(q)
        result['data']=data
    else:result['status']=freshness(ds,datetime.now(TZ),state)
    # 时间状态进入ETag，防止未改文件却永远显示旧的ok。
    result['revision']=revision(result)
    return result


def _store_section(path,key,value):
    target=market_path(path)
    with _cache_write_lock, core.lock(target):
        try:cache=core.read_json(target,{'schema_version':1,'sections':{}})
        except ValueError:cache={'schema_version':1,'sections':{}}
        cache.setdefault('sections',{})[key]=value
        core.write_json(target,cache)


def legacy_series(ds):
    cols=['time','open','close','high','low','volume','amount']
    return dict(source=ds['source'],updated_at=ds['retrieved_at'],count=len(ds['data']),
        bars=[[r.get(k) for k in cols] for r in ds['data']],columns=cols,
        currency=ds.get('currency') or (ds.get('data') or [{}])[0].get('currency'),timezone=ds['timezone'],adjustment=ds.get('adjustment'),
        volume_unit=ds.get('volume_unit'),amount_unit=ds.get('amount_unit'),
        precision=ds.get('precision'),status=ds['status'],reason=ds.get('reason'),normalized=ds)


class Collector:
    def __init__(self,path,clock=time.monotonic):
        self.path=Path(path);self.clock=clock
        self.tasks={};self.busy=threading.Lock();self._requests=set();self._requests_lock=threading.Lock()
        # 从磁盘恢复按需产品，避免重启时把已经下载的排行K线当作无关数据删除。
        existing=core.load_cache(self.path).get('series',{})
        self._demand={s:self.clock() for s in existing if self.kline_periods(s)}
        self._force_next=False;self._last_manual=-1000.

    @staticmethod
    def kline_periods(symbol):
        if symbol.startswith(('SH:','SZ:','BJ:')):return ('day','m5')
        return ('day',) if symbol in public.TX_GLOBAL else ()

    def kline_state(self,symbol,period='day',adjustment='raw',entry=None):
        if period not in self.kline_periods(symbol) or (adjustment=='qfq' and not symbol.startswith(('SH:','SZ:','BJ:'))):
            return dict(status='unsupported',pending=False,kind='unsupported',message='该产品暂无可用K线接口')
        entry=entry if entry is not None else core.load_cache(self.path).get('series',{}).get(symbol,{})
        entry=entry or {};name=period if adjustment=='raw' else period+'_qfq'
        error=entry.get('errors',{}).get(name)
        if entry.get(name,{}).get('bars'):
            return dict(status='stale' if error else 'ready',pending=False,kind=error.get('kind') if error else None,message=error['message'] if error else None)
        if error:return dict(error,status='failed',pending=False)
        return dict(status='pending',pending=True,message='正在获取K线…')

    @staticmethod
    def failure(exc):
        if isinstance(exc,HTTPError):
            if exc.code in (401,403):return 'permission','接口权限受限，暂时无法访问'
            if exc.code==429:return 'rate_limit','行情接口请求受限，请稍后刷新'
        if isinstance(exc,TimeoutError):return 'timeout','行情接口超时，暂时无法访问'
        if isinstance(exc,ValueError):return 'no_data','行情源暂未返回可用K线'
        return 'network','行情接口连接失败，暂时无法访问'

    def prefetch(self,symbols):
        """预热当前页面的产品，不下载全市场；最多50项，持仓/自选优先。"""
        tracked={r['symbol'] for r in tracked_products(self.path)}
        wanted=list(dict.fromkeys(s for s in symbols if self.kline_periods(s)))
        series=core.load_cache(self.path).get('series',{})
        with self._requests_lock:
            protected=tracked|set(wanted)
            for symbol in wanted:
                if symbol in tracked:continue  # 常规调度已经覆盖。
                if symbol not in self._demand:
                    if len(tracked|set(self._demand))>=50:
                        cold=[s for s in self._demand if s not in protected]
                        if not cold:continue
                        self._demand.pop(min(cold,key=self._demand.get))
                    if self.kline_state(symbol,entry=series.get(symbol,{}))['status'] not in ('failed','unsupported'):
                        self._requests.update(f'kline:{symbol}:{period}:raw' for period in self.kline_periods(symbol))
                self._demand[symbol]=self.clock()

    def queue(self,key):
        with self._requests_lock:
            if key.startswith('kline:'):
                parts=key.split(':')
                if len(parts)!=5 or parts[3] not in ('day','m5') or parts[4] not in ('raw','qfq'):raise ValueError('无效K线任务')
                symbol=validate_symbol(parts[1]+':'+parts[2])
                tracked={r['symbol'] for r in tracked_products(self.path)}
                if len(tracked|set(self._demand)|{symbol})>50:raise ValueError('跟踪与按需产品合计已达50项')
                self._demand[symbol]=self.clock()
            self._requests.add(key)

    def request_refresh(self):
        with self._requests_lock:
            if self.clock()-self._last_manual>=60:
                self._force_next=True;self._last_manual=self.clock()

    def update_section(self,key,fetcher,force=False,interval=300):
        task=self.tasks.setdefault(key,{'due':0,'failures':0,'retry_at':0})
        now=self.clock()
        if not key.startswith('kline:') and not force and read_section(self.path,key).get('error_kind')=='permission':return None
        if key.startswith('kline:') and not force:
            _,market,code,period,adjustment=key.split(':');symbol=market+':'+code
            entry=core.load_cache(self.path).get('series',{}).get(symbol,{})
            state=self.kline_state(symbol,period,adjustment,entry)
            if state['status']=='unsupported':return None
            error=entry.get('errors',{}).get(period if adjustment=='raw' else period+'_qfq',{})
            if error.get('kind')=='permission' or (error.get('retry_at') and error['retry_at']>core.now()):return None
        if (now<task['retry_at'] and (not force or not key.startswith('kline:'))) or (not force and now<task['due']):return None
        try:
            value=fetcher()
            if not isinstance(value,dict) or 'data' not in value:raise ValueError('无效数据集')
            if not key.startswith('kline:'):_store_section(self.path,key,value)
            symbol=':'.join(key.split(':')[1:3]) if key.startswith('kline:') else None
            task.update(failures=0,retry_at=0,due=self.clock()+interval,status=value.get('status'),
                        session_state=market_state(symbol),session_key=session_key(symbol))
            task.pop('kind',None)
            return value
        except (OSError,ValueError,KeyError,IndexError,TypeError,ArithmeticError) as exc:
            if isinstance(exc,HTTPError):exc.close()
            kind,message=self.failure(exc)
            task['failures']+=1
            task['due']=self.clock()+60
            if task['failures']>=3:task['retry_at']=self.clock()+900
            if key.startswith('kline:'):
                _,market,code,period,adjustment=key.split(':');symbol=market+':'+code
                task['kind']=kind
                task['retry_at']=self.clock()+900
                error=dict(kind=kind,message=message,failed_at=core.now(),
                    retry_at=(datetime.now(TZ)+timedelta(minutes=15)).isoformat(timespec='seconds'))
                with _cache_write_lock,core.lock(self.path):
                    cache=core.load_cache(self.path);entry=cache.setdefault('series',{}).setdefault(symbol,{'name':symbol})
                    name=period if adjustment=='raw' else period+'_qfq'
                    entry.setdefault('errors',{})[name]=error
                    if name in entry:
                        entry[name].update(status='stale',reason=message)
                        if entry[name].get('normalized'):entry[name]['normalized'].update(status='stale',reason=message)
                    core.save_cache(self.path,cache)
                task['status']='stale'
                return {'status':'stale','data':[],'reason':type(exc).__name__}
            previous=read_section(self.path,key)
            prior=dict(previous,status='stale' if previous.get('data') else 'unavailable',
                reason=message.replace('K线','数据'),error_kind=kind,last_attempt=core.now())
            _store_section(self.path,key,prior)
            return prior

    def _quotes(self,force=False):
        tracked=tracked_products(self.path)
        old=core.load_cache(self.path).get('quotes',{})
        needed=[];quotes={}
        for row in tracked:
            symbol=row['symbol'];prior=old.get(symbol,{}).get('normalized_quote')
            stamp=(prior or {}).get('source_as_of')
            local_stamp=datetime.fromisoformat(stamp).astimezone(ZoneInfo(product_meta(symbol)['timezone'])) if stamp else None
            final=local_stamp and local_stamp.date().isoformat()==session_key(symbol) and local_stamp.hour>=product_meta(symbol)['close_hour']
            from 数据源 import 华泰 as ht
            policy_changed=ht.configured() and (prior or {}).get('routing',{}).get('primary')!='华泰Skill'
            if prior and market_state(symbol)=='closed' and final and not force and not policy_changed:
                quotes[symbol]=prior
            else:needed.append(symbol)
        if needed:quotes.update(public.fetch_quotes(needed))
        now=core.now()
        with _cache_write_lock,core.lock(self.path):
            cache=core.load_cache(self.path)
            for key,q in quotes.items():
                # 账户旧读模型涨跌字段为百分数；公共契约为小数，仅边界转换一次。
                cache.setdefault('quotes',{})[key]=dict(q,requested_at=now,market_time=q.get('source_as_of'),
                    change_pct=str(Decimal(q['change_pct'])*100) if q.get('change_pct') is not None else None,
                    normalized_quote=q)
            cache['last_quote_attempt']=now
            cache['quote_errors']=[{'symbol':r['symbol'],'category':'missing'} for r in tracked if r['symbol'] not in quotes]
            core.save_cache(self.path,cache)
        rows=[]
        for r in tracked:
            if r['symbol'] in quotes:rows.append(dict(quotes[r['symbol']],product_type=r.get('product_type'),display_name=r.get('name')))
        sources=' / '.join(dict.fromkeys(q.get('source','未知') for q in rows))
        return dataset('overview',rows,sources,coverage={'requested':len(tracked),'returned':len(rows),'complete':len(rows)==len(tracked),
            'huatai':sum(q.get('routing',{}).get('used_primary',False) for q in rows)})

    def kline(self,symbol,period='day',adjustment='raw'):
        validate_symbol(symbol)
        if period not in ('day','m5') or adjustment not in ('raw','qfq'):raise ValueError('无效K线参数')
        params=dict(symbol=symbol,period=period,adjustment=adjustment,count=400 if period=='day' else 2400)
        ds=public.fetch('kline',params)
        if not ds.get('data'):raise ValueError('K线无可用数据')
        key=period if adjustment=='raw' else period+'_qfq'
        with _cache_write_lock,core.lock(self.path):
            cache=core.load_cache(self.path);entry=cache.setdefault('series',{}).setdefault(symbol,{'name':symbol})
            previous=(entry.get(key) or {}).get('normalized')
            # qfq全观察窗重取，避免复权因子变化污染已缓存尾部。
            merged=merge_series(previous if adjustment=='raw' else None,ds,400 if period=='day' else 2400)
            entry[key]=legacy_series(merged)
            entry.get('errors',{}).pop(key,None)
            if not entry.get('errors'):entry.pop('errors',None)
            core.save_cache(self.path,cache)
        return ds

    def run(self,sections=None,force=False):
        if not self.busy.acquire(blocking=False):return {'busy':True}
        try:
            with self._requests_lock:
                force=force or self._force_next;self._force_next=False
            jobs={
                'overview':(lambda:self._quotes(force),60),
                'news':(lambda:public.fetch('news',{}),300),
                'sectors:industry':(lambda:public.fetch('sectors',{'group':'industry'}),300)}
            for product in ('stock','etf','lof'):
                for sort in ('up','down','amount','turnover'):
                    key=f'ranks:{product}:{sort}'
                    jobs[key]=(lambda p=product,s=sort:public.fetch('ranks',{'product_type':p,'sort':s}),300)
            tracked=tracked_products(self.path)
            current={row['symbol'] for row in tracked}
            with self._requests_lock:
                # 当前持仓/自选优先，按需段总量有界；不清除事实。
                spare=max(0,50-len(current))
                extras=sorted((s for s in self._demand if s not in current),key=lambda s:self._demand[s],reverse=True)[:spare]
                keep=current|set(extras);self._demand={s:v for s,v in self._demand.items() if s in keep}
            with _cache_write_lock,core.lock(self.path):
                cache=core.load_cache(self.path)
                for field in ('quotes','series'):
                    cache[field]={s:v for s,v in cache.get(field,{}).items() if s in keep}
                for symbol,entry in cache.get('series',{}).items():
                    for period,meta in list(entry.items()):
                        if isinstance(meta,dict) and 'bars' in meta:
                            entry[period]=normalize_cached_series(symbol,meta,datetime.now(TZ))
                core.save_cache(self.path,cache)
            for key in list(self.tasks):
                parts=key.split(':')
                if len(parts)>=3 and parts[0] in ('kline','nav','announcements') and ':'.join(parts[1:3]) not in keep:
                    del self.tasks[key]
            target=market_path(self.path)
            with _cache_write_lock,core.lock(target):
                try:stored=core.read_json(target,{'schema_version':1,'sections':{}})
                except ValueError:stored={'schema_version':1,'sections':{}}
                old_sections=stored.get('sections',{})
                clean={k:v for k,v in old_sections.items() if k not in ('flows','sectors:concept') and not k.startswith('announcements:') and not k.startswith('kline:') and
                    not (k.split(':')[0] in ('nav','announcements') and ':'.join(k.split(':')[1:3]) not in keep)}
                if clean!=old_sections:
                    stored['sections']=clean;core.write_json(target,stored)
            for row in tracked:
                symbol=row['symbol']
                if symbol.startswith(('SH:','SZ:','BJ:')) or symbol in public.TX_GLOBAL:
                    for period in ('day','m5') if symbol.startswith(('SH:','SZ:','BJ:')) else ('day',):
                        key=f'kline:{symbol}:{period}:raw'
                        jobs[key]=(lambda s=symbol,p=period:self.kline(s,p,'raw'),300)
                if row.get('product_type')=='holding':
                    if symbol.split(':')[1].startswith(('5','15','16')):
                        jobs['nav:'+symbol]=(lambda s=symbol:east.fetch('nav',{'symbol':s}),3600)
            for symbol in extras:
                for period in self.kline_periods(symbol):
                    jobs[f'kline:{symbol}:{period}:raw']=(lambda s=symbol,p=period:self.kline(s,p,'raw'),300)
            # 曾打开过的前复权段也随刷新更新，不在每次打开时重下载。
            for symbol in keep:
                if cache.get('series',{}).get(symbol,{}).get('day_qfq'):
                    jobs[f'kline:{symbol}:day:qfq']=(lambda s=symbol:self.kline(s,'day','qfq'),300)
            with self._requests_lock:
                requested=set(self._requests);self._requests.clear()
            for key in requested:
                if key.startswith('kline:'):
                    _,market,code,period,adjustment=key.split(':')
                    symbol=market+':'+code
                    jobs[key]=(lambda s=symbol,p=period,a=adjustment:self.kline(s,p,a),300)
            jobs={k:v for k,v in jobs.items() if not k.startswith('kline:') or ':'.join(k.split(':')[1:3]) in keep}
            requested={k for k in requested if k in jobs}
            keys=sorted(requested,key=lambda k:(':m5:' in k,':qfq' in k,k))+[k for k in jobs if k not in requested]
            start=self.clock();out={}
            def execute(key):
                task=self.tasks.get(key)
                # 闭市已有成功值则无需重复；失败仍允许有界恢复。境外时段未知只按刷新预算。
                symbol=':'.join(key.split(':')[1:3]) if key.startswith('kline:') else None
                if symbol and not force and (self.tasks.get(f'kline:{symbol}:day:raw',{}).get('kind')=='permission'
                        or cache.get('series',{}).get(symbol,{}).get('errors',{}).get('day',{}).get('kind')=='permission'):
                    return key,None
                state=market_state(symbol)
                if (not force and key not in requested and task and task.get('failures',0)==0 and
                    state=='closed' and task.get('session_state')=='closed' and
                    task.get('session_key')==session_key(symbol) and key.split(':')[0] not in ('overview','news','announcements','nav')):return key,None
                fetcher,interval=jobs[key]
                value=self.update_section(key,fetcher,force or key in requested,interval)
                return key,value
            keys=[k for k in keys if k in jobs and (not sections or k.split(':')[0] in sections or k in sections)]
            # 每批最多四项；报价/快讯与慢K线不会在同一个串行队列中互相阻塞。
            with ThreadPoolExecutor(max_workers=4) as pool:
                for index in range(0,len(keys),4):
                    if self.clock()-start>=20:
                        with self._requests_lock:self._requests.update(keys[index:])
                        break
                    for key,value in pool.map(execute,keys[index:index+4]):
                        if value is not None:out[key]=value.get('status')
            core.observe_account(self.path)
            return {'sections':out,'报价失败':[],'K线失败':[]}
        finally:self.busy.release()


def collector(path=core.DEFAULT):
    key=str(Path(path).resolve())
    with _engine_lock:
        if key not in _engines:_engines[key]=Collector(path)
        return _engines[key]


def sync(data_root,sections=None,force=False):
    return collector(account_path(data_root)).run(sections,force)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('show','refresh'))
    parser.add_argument('--section',default='overview')
    parser.add_argument('--file',type=Path,default=core.DEFAULT)
    args=parser.parse_args()
    if args.command=='refresh':sync(args.file,(args.section,),True)
    print(json.dumps(read_section(args.file,args.section),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
