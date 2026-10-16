"""华泰技能只读报价适配器。协议来自已校验官方getQuote脚本，未实现交易接口。"""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from datetime import datetime
import json
import os
from pathlib import Path
import threading
import time
from 数据契约 import decimal_text, ratio, validate_symbol, TZ

ENDPOINT='https://ai.zhangle.com/edge/entry/gate/api/simSkills/getQuote'
SKILL_CODE='mx_1778741794549'
_lock=threading.Lock()
_blocked_until=0.0
_key_tag=None


def 程序配置():
    """程序目录共享配置：独立仓库或安装目录下的`配置.json`。"""
    import sys
    if getattr(sys,'frozen',False):
        return Path(sys.executable).parent/'配置.json'
    return Path(__file__).resolve().parents[2]/'配置.json'


def key():
    """密钥优先级：环境变量 > 程序目录配置.json > 用户目录.htsc-skills/config。"""
    value=os.environ.get('HT_APIKEY','').strip()
    if value:return value
    path=程序配置()
    if path.is_file():
        try:
            value=str(json.loads(path.read_text(encoding='utf-8')).get('HT_APIKEY') or '').strip()
        except (OSError,ValueError,AttributeError,TypeError):
            value=''
        if value:return value
    path=Path.home()/'.htsc-skills/config'
    if path.is_file():
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip().startswith('HT_APIKEY='):return line.split('=',1)[1].strip()
    return ''


def configured():
    return os.environ.get('HTSC_MARKET_MODE','auto')!='public' and bool(key())


def _post(symbol, secret):
    market,code=symbol.split(':')
    body=json.dumps({'stockCode':code,'exchange':market}).encode()
    # 禁止携带密钥跟随HTTP跳转；网关地址固定，不从前端接收URL。
    import requests
    response=requests.post(ENDPOINT,data=body,headers={'apiKey':secret,'skillCode':SKILL_CODE,'Content-Type':'application/json'},timeout=6,allow_redirects=False)
    if response.status_code!=200:
        return {'ok':False,'error':{'category':'auth' if response.status_code in (401,403) else 'network','message':f'HTTP {response.status_code}'}}
    return response.json()


def normalized(symbol, payload, reference=None):
    validate_symbol(symbol)
    raw=payload['data'];price=decimal_text(raw['currentPrice'],positive=True)
    if not raw.get('stockName') or not price:raise ValueError('报价字段缺失')
    from .公共行情 import quote
    base=quote(symbol,str(raw['stockName']),price)
    base.update(reference or {})
    fields={k:base.get('source') for k,v in base.items() if v is not None}
    base.update(symbol=symbol,name=str(raw['stockName']),price=price,source='华泰Skill getQuote',
        source_as_of=None,source_time_kind='unknown',source_local_time=None,status='unknown',
        retrieved_at=datetime.now(TZ).isoformat(timespec='seconds'),
        quote_time_note='华泰未返回行情时点；采集时间不代替行情时间',
        primary_response={k:raw.get(k) for k in ('stockName','currentPrice','prevClose','limitUp','limitDown','bidPrice1','askPrice1','change','isSuspended')})
    base['change_pct']=ratio(raw.get('change'))
    mapping={'prevClose':'prev_close','limitUp':'limit_up','limitDown':'limit_down','bidPrice1':'bid1','askPrice1':'ask1'}
    for old,new in mapping.items():
        value=decimal_text(raw.get(old))
        if value is not None:base[new]=value
        elif new not in base:base[new]=None
    base['suspended']=raw.get('isSuspended') if isinstance(raw.get('isSuspended'),bool) else None
    for name in ('name','price','change_pct','suspended'):
        fields[name]='华泰Skill getQuote'
    for old,new in mapping.items():
        if raw.get(old) is not None:fields[new]='华泰Skill getQuote'
    if reference:
        base['reference_quote']={k:reference.get(k) for k in ('source','source_as_of','price','prev_close','change_pct')}
        base['reference_quote']['matches_price']=Decimal(str(reference.get('price')))==Decimal(price) if reference.get('price') else False
        fields['source_as_of']=None
    base.update(source_fields=fields,currency=base.get('currency') or 'CNY',precision=len(price.partition('.')[2]))
    return base


def fetch(symbols, references):
    """返回成功主源和原因；无认证/不支持/失败由调用者保留原补充源。"""
    global _key_tag,_blocked_until
    secret=key()
    if not configured():return {},{'status':'not_configured','reason':'未配置华泰密钥，保留公开补充源'}
    import hashlib
    tag=hashlib.sha256(secret.encode()).hexdigest()
    with _lock:
        if tag!=_key_tag:_key_tag=tag;_blocked_until=0
        if time.monotonic()<_blocked_until:return {},{'status':'backoff','reason':'华泰暂不可用，退避后重试'}
    wanted=[s for s in symbols if s.startswith(('SH:','SZ:','BJ:'))]
    started=time.monotonic();errors=[]
    def one(symbol):
        if time.monotonic()-started>10:return symbol,None,'budget'
        try:
            value=_post(symbol,secret)
            if value.get('ok') is not True:return symbol,None,(value.get('error') or {}).get('category','business')
            return symbol,normalized(symbol,value,references.get(symbol)),None
        except Exception:
            return symbol,None,'network_or_schema'
    with ThreadPoolExecutor(max_workers=4) as pool:
        result=list(pool.map(one,wanted))
    rows={}
    for symbol,row,error in result:
        if row:rows[symbol]=row
        else:errors.append({'symbol':symbol,'category':error})
    if any(x['category']=='auth' for x in errors) or (wanted and not rows):
        with _lock:_blocked_until=time.monotonic()+300
    return rows,dict(status='ok' if len(rows)==len(wanted) else 'partial',returned=len(rows),requested=len(wanted),errors=errors)
