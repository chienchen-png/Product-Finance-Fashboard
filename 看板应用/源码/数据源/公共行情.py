"""腾讯与新浪只读适配。文本协议按白名单解析，缺字段不填零。"""
from datetime import datetime, timedelta
from decimal import Decimal
import html
import json
import re
from urllib.parse import urlencode, urlsplit
from 数据契约 import TZ, dataset, decimal_text as num, ratio, validate_symbol, product_meta, bar_close_time
from . import request, get_json

BENCHMARKS = [
    ('SH:000001','上证指数','index'),('SZ:399001','深证成指','index'),
    ('SZ:399006','创业板指','index'),('INDEX:HSI','恒生指数','index'),
    ('INDEX:HSTECH','恒生科技','index'),('INDEX:NDX','纳斯达克100','index'),
    ('INDEX:INX','标普500','index'),('FX:USDCNY','美元/人民币','fx'),('FUT:GC','纽约黄金','future')]
TX_GLOBAL={'INDEX:HSI':'hkHSI','INDEX:HSTECH':'hkHSTECH','INDEX:NDX':'usNDX','INDEX:INX':'usINX'}
EASTMONEY_KLINE=('https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}'
    '&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57&klt={klt}&fqt={fqt}&end=20500101&lmt={count}')
EASTMONEY_KLT={'day':101,'m5':5}


def tx_symbol(symbol):
    validate_symbol(symbol)
    if symbol in TX_GLOBAL:return TX_GLOBAL[symbol]
    market,code=symbol.split(':')
    if market in ('SH','SZ','BJ','HK'):return market.lower()+code
    raise ValueError('此报价源未支持该产品')


def eastmoney_day_amounts(symbol, count):
    """东财日线成交额，只补腾讯日K缺失的成交额字段；不替代价格来源。"""
    market,code=symbol.split(':')
    secid=('1.' if market=='SH' else '0.')+code
    payload=get_json(EASTMONEY_KLINE.format(secid=secid,klt=101,fqt=1,count=min(int(count),400)),
        referer='https://quote.eastmoney.com/')
    rows=(payload.get('data') or {}).get('klines') or []
    out={}
    for line in rows:
        parts=str(line).split(',')
        if len(parts)<7:continue
        amount=num(parts[6])
        if amount is not None:out[parts[0]]=amount
    return out


def eastmoney_kline(symbol, period, adjustment, count):
    """北交所价量：腾讯无历史，改用东财；复权模式按请求取fqt，成交额单位CNY。"""
    market,code=symbol.split(':')
    secid=('1.' if market=='SH' else '0.')+code
    limit=640 if period=='m5' else 400
    size=min(int(count),limit)
    payload=get_json(EASTMONEY_KLINE.format(secid=secid,klt=EASTMONEY_KLT[period],
        fqt=1 if adjustment=='qfq' else 0,count=size),referer='https://quote.eastmoney.com/')
    raw=((payload.get('data') or {}).get('klines')) or []
    now=datetime.now(TZ);product=product_meta(symbol);rows=[]
    for line in raw[-size:]:
        parts=str(line).split(',')
        if len(parts)<7:continue
        stamp=parts[0]
        close_at=bar_close_time(stamp,period,symbol)
        rows.append(dict(time=stamp,open=num(parts[1]),close=num(parts[2]),high=num(parts[3]),low=num(parts[4]),
            volume=None,amount=num(parts[6]),closed=close_at<=now,adjustment=adjustment,
            currency=product['currency'],closed_at=close_at.isoformat(),timezone=product['timezone'],
            precision=len(parts[2].partition('.')[2]),volume_unit=None,amount_unit='CNY'))
    if not rows:raise ValueError('K线缺失或复权模式不符')
    return dataset('kline',rows,'东方财富K线',symbol=symbol,period=period,adjustment=adjustment,
        timezone=product['timezone'],currency=product['currency'],calendar_verified=product['calendar_verified'],
        precision=min(r['precision'] for r in rows),volume_unit=None,amount_unit='CNY')


def quote(symbol, name, price, **fields):
    validate_symbol(symbol)
    price=num(price,positive=True)
    if price is None:raise ValueError('现价缺失')
    market=symbol.split(':')[0]
    currency='HKD' if market=='HK' or symbol in ('INDEX:HSI','INDEX:HSTECH') else (
        'USD' if symbol in ('INDEX:NDX','INDEX:INX','FUT:GC') else 'CNY')
    return dict(symbol=symbol,name=name,price=price,prev_close=None,change_pct=None,open=None,high=None,low=None,
        volume=None,amount=None,currency=currency,volume_unit=None,amount_unit=None,
        precision=len(price.partition('.')[2]),source_as_of=None,source_time_kind='unknown',
        source=None,retrieved_at=datetime.now(TZ).isoformat(timespec='seconds'),**fields)


def parse_tencent(text, symbols):
    wanted={tx_symbol(s):s for s in symbols}
    rows={}
    for code,raw in re.findall(r'v_([A-Za-z0-9_]+)="([^"\r\n]*)";',text):
        if code not in wanted:continue
        v=raw.split('~')
        if len(v)<35:continue
        symbol=wanted[code]
        try:
            q=quote(symbol,v[1],v[3])
            q.update(prev_close=num(v[4],positive=True),open=num(v[5]),high=num(v[33]),low=num(v[34]),
                change_pct=ratio(v[32]),source='腾讯网页行情',source_local_time=v[30])
            if code.startswith(('sh','sz','bj')):
                q.update(volume=num(Decimal(v[6])*100) if v[6] else None, volume_unit='shares',
                    amount=num(Decimal(v[37])*10000) if len(v)>37 and v[37] else None,amount_unit='CNY',
                    bid1=num(v[9]) if v[9] else None,ask1=num(v[19]) if v[19] else None)
                stamp=datetime.strptime(v[30],'%Y%m%d%H%M%S').replace(tzinfo=TZ)
                q.update(source_as_of=stamp.isoformat(),source_time_kind='provider_update')
            elif code.startswith('hk'):
                stamp=datetime.strptime(v[30],'%Y/%m/%d %H:%M:%S').replace(tzinfo=TZ)
                q.update(source_as_of=stamp.isoformat(),source_time_kind='provider_update')
            # 美股原串无时区：保留原文，不猜其为北京时间或纽约时间。
            rows[symbol]=q
        except (ValueError, ArithmeticError):continue
    return rows


def parse_sina(text, symbols):
    wanted={s.split(':')[0].lower()+s.split(':')[1]:s for s in symbols if s.startswith(('SH:','SZ:','BJ:','HK:'))}
    wanted.update({'fx_susdcny':'FX:USDCNY','hf_GC':'FUT:GC'})
    out={}
    for code,raw in re.findall(r'hq_str_([A-Za-z0-9_$]+)="([^"\r\n]*)";',text):
        symbol=wanted.get(code)
        if symbol not in symbols:continue
        v=raw.split(',')
        try:
            if code.startswith(('sh','sz','bj')):
                q=quote(symbol,v[0],v[3]); prev=num(v[2],positive=True)
                q.update(open=num(v[1]),prev_close=prev,high=num(v[4]),low=num(v[5]),
                    volume=num(v[8]),amount=num(v[9]),volume_unit='shares',amount_unit='CNY',
                    bid1=num(v[6]),ask1=num(v[7]),
                    change_pct=num(Decimal(v[3])/Decimal(prev)-1) if prev else None)
                stamp=v[30]+'T'+v[31]+'+08:00'
            elif code=='fx_susdcny':
                q=quote(symbol,v[9],v[8]);q.update(prev_close=num(v[3]),open=num(v[5]),
                    high=num(v[6]),low=num(v[7]),change_pct=ratio(v[10]),reference_note=v[13])
                stamp=v[17]+'T'+v[0]+'+08:00'
            elif code=='hf_GC':
                q=quote(symbol,v[13],v[0]);q.update(high=num(v[4]),low=num(v[5]),reference_note='黄金期货参考价，非ETF价',price_unit='USD/oz')
                stamp=v[12]+'T'+v[6]+'+08:00'
            else:continue  # 港股字段契约未核，不套用A股格式。
            datetime.fromisoformat(stamp)
            q.update(source='新浪网页行情',source_as_of=stamp,source_time_kind='provider_update')
            out[symbol]=q
        except (ValueError,IndexError,ArithmeticError):continue
    return out


def _fetch_public_quotes(symbols):
    symbols=list(dict.fromkeys(symbols))
    if len(symbols)>50:raise ValueError('跟踪产品超过50项')
    rows={}
    tx=[s for s in symbols if not s.startswith(('FX:','FUT:'))]
    errors=[]
    for start in range(0,len(tx),20):
        batch=tx[start:start+20]
        try:
            rows.update(parse_tencent(request('https://qt.gtimg.cn/q='+','.join(tx_symbol(s) for s in batch),encoding='gb18030'),batch))
        except (OSError,ValueError) as exc:errors.append(type(exc).__name__)
    missing=[s for s in symbols if s not in rows and (s.startswith(('SH:','SZ:','BJ:','FX:','FUT:')))]
    if missing:
        mapping={'FX:USDCNY':'fx_susdcny','FUT:GC':'hf_GC'}
        codes=[mapping.get(s,s.split(':')[0].lower()+s.split(':')[1]) for s in missing]
        try:rows.update(parse_sina(request('https://hq.sinajs.cn/list='+','.join(codes),encoding='gb18030'),missing))
        except (OSError,ValueError) as exc:errors.append(type(exc).__name__)
    if not rows:raise ValueError('无有效报价 '+','.join(errors))
    return rows


def fetch_quotes(symbols):
    """华泰已配置则优先报价；公开源保留补充字段、独立时间核对及失败回退。"""
    from . import 华泰 as ht
    symbols=list(dict.fromkeys(symbols))
    if len(symbols)>50:raise ValueError('跟踪产品超过50项')
    primary,state=ht.fetch(symbols,{})
    try:references=_fetch_public_quotes(symbols)
    except (OSError,ValueError):references={}
    rows=dict(references)
    for symbol,row in primary.items():
        rows[symbol]=ht.normalized(symbol,{'data':row['primary_response']},references.get(symbol))
    for symbol,row in rows.items():
        row['routing']={'primary':'华泰Skill','used_primary':symbol in primary,
            'primary_status':state['status'],
            'fallback_reason':None if symbol in primary else ('该市场/产品未取得华泰结构化报价' if state['status']!='not_configured' else state['reason'])}
    if not rows:raise ValueError('华泰与公开补充源均未返回有效报价')
    return rows


def parse_ranks(raw, kind, sort):
    if not isinstance(raw,list):raise ValueError('排行榜结构变化')
    rows=[]
    for v in raw[:20]:
        code=str(v.get('symbol',''))
        if not re.fullmatch(r'(sh|sz|bj)\d{6}',code):continue
        symbol=code[:2].upper()+':'+code[2:]
        rows.append(dict(id=symbol,symbol=symbol,name=str(v.get('name','')),product_type=kind,
            price=num(v.get('trade'),positive=True),change_pct=ratio(v.get('changepercent')),
            amount=num(v.get('amount')),turnover_rate=ratio(v.get('turnoverratio')),
            main_net=None,source_clock=v.get('ticktime'),currency='CNY',amount_unit='CNY'))
    if not rows:raise ValueError('排行榜为空或字段变化')
    return dataset('ranks',rows,'新浪行情中心',status='unknown',reason='来源仅含时分秒，交易日期待核',
        coverage={'product_type':kind,'sort':sort,'returned':len(rows),'complete':False,'scope':'新浪节点，含供应商纳入的市场'})


def clean_text(value):
    s=re.sub(r'<(script|style)\b[^>]*>.*?</\1\s*>','',str(value),flags=re.I|re.S)
    return html.unescape(re.sub(r'<[^>]+>','',s)).strip()


def safe_url(value):
    value=str(value or '')
    return value if urlsplit(value).scheme in ('http','https') and urlsplit(value).hostname else None


def parse_news(raw):
    items=raw['result']['data']['feed']['list'];rows=[]
    now=datetime.now(TZ)
    for item in items[:100]:
        stamp=str(item.get('create_time','')).replace(' ','T')
        try:published=datetime.fromisoformat(stamp).replace(tzinfo=TZ)
        except ValueError:continue
        if now-published>timedelta(days=7):continue
        text=clean_text(item.get('rich_text',''))
        if not text:continue
        try:ext=json.loads(item.get('ext') or '{}')
        except (TypeError,ValueError):ext={}
        if not isinstance(ext,dict):ext={}
        rows.append(dict(id=str(item['id']),title=text[:140],summary=text[:300],source='新浪财经',
            url=safe_url(item.get('docurl') or ext.get('docurl')),published_at=published.isoformat(),
            date_precision='second',retrieved_at=now.isoformat(timespec='seconds'),symbols=[],association_type='none'))
    latest=max((r['published_at'] for r in rows),default=None)
    return dataset('news',rows,'新浪7×24',source_as_of=latest,source_time_kind='publication',
        status='ok' if rows else 'unavailable',reason=None if rows else '无近期快讯')


def parse_industry(text):
    """新浪行业公开表；成交额已与成分股逐项合计交叉核验。"""
    match=re.fullmatch(r'\s*var S_Finance_bankuai_sinaindustry\s*=\s*(\{.*\})\s*;?\s*',text,re.S)
    if not match:raise ValueError('行业响应格式变化')
    raw=json.loads(match.group(1));rows=[]
    for key,value in raw.items():
        v=str(value).split(',')
        if len(v)!=13 or v[0]!=key:raise ValueError('行业字段变化')
        amount=num(v[7]);members=int(v[2])
        if amount is None or Decimal(amount)<0 or members<=0:raise ValueError('行业数量或成交额无效')
        rows.append(dict(id=key,name=v[1],product_type='sector',classification='industry',level=None,
            member_count=members,change_pct=ratio(v[5]),amount=amount,amount_unit='CNY',
            turnover_rate=None,main_net=None,leader_symbol=v[8][:2].upper()+':'+v[8][2:],leader_name=v[12]))
    if not rows:raise ValueError('行业数据为空')
    rows.sort(key=lambda r:Decimal(r['change_pct']) if r['change_pct'] is not None else Decimal('-999'),reverse=True)
    return dataset('sectors',rows,'新浪行业行情',status='unknown',reason='接口未提供行情日期与时刻',
        coverage={'group':'industry','total':len(rows),'returned':len(rows),'complete':True,
                  'scope':'新浪行业分类；非全A市场情绪统计'},amount_unit='CNY')


def fetch(kind, params):
    if kind=='sectors':
        if params.get('group','industry')!='industry':raise ValueError('当前仅启用已核验的新浪行业')
        return parse_industry(request('https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php',encoding='gb18030',
            referer='https://vip.stock.finance.sina.com.cn/mkt/'))
    if kind=='quotes':
        rows=fetch_quotes(params['symbols'])
        return dataset('quotes',list(rows.values()),'腾讯/新浪',coverage={'requested':len(params['symbols']),'returned':len(rows)})
    if kind=='news':return parse_news(get_json('https://zhibo.sina.com.cn/api/zhibo/feed?zhibo_id=152&tag_id=0&page=1&page_size=100'))
    if kind=='ranks':
        product=params.get('product_type','stock');sort=params.get('sort','up')
        node={'stock':'hs_a','etf':'etf_hq_fund','lof':'lof_hq_fund'}[product]
        field={'up':'changepercent','down':'changepercent','amount':'amount','turnover':'turnoverratio'}[sort]
        query=dict(page=1,num=20,sort=field,asc=int(sort=='down'),node=node,symbol='',_s_r_a='page')
        return parse_ranks(get_json('https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?'+urlencode(query),encoding='gb18030'),product,sort)
    if kind=='kline':
        symbol=params['symbol'];period=params.get('period','day');adjustment=params.get('adjustment','raw')
        if period not in ('day','m5') or adjustment not in ('raw','qfq'):raise ValueError('周期/复权不支持')
        key=tx_symbol(symbol);count=min(params.get('count',120),640 if period=='m5' else 400)
        if symbol.startswith('BJ:'):
            # 腾讯无北交所历史；北交所统一走东财，避免行情页个股长期空白。
            return eastmoney_kline(symbol,period,adjustment,count)
        if period=='day':
            segment='hkfqkline' if key.startswith('hk') else 'usfqkline' if key.startswith('us') else 'fqkline'
            # 港美端点需带qfq请求模式；raw仅读取明确返回的day字段，不拿qfqday冒充原始价。
            mode='qfq' if adjustment=='qfq' or key.startswith(('hk','us')) else ''
            url=f'https://web.ifzq.gtimg.cn/appstock/app/{segment}/get?param={key},day,,,{count},{mode}'
        else:
            if not symbol.startswith(('SH:','SZ:','BJ:')):raise ValueError('该市场分钟线未验证')
            url=f'https://ifzq.gtimg.cn/appstock/app/kline/mkline?param={key},m5,,{count}'
        node=get_json(url)['data'][key]
        raw=node.get('qfqday') if period=='day' and adjustment=='qfq' else node.get(period)
        if not raw:raise ValueError('K线缺失或复权模式不符')
        amounts={}
        if period=='day' and symbol.startswith(('SH:','SZ:')):
            try:amounts=eastmoney_day_amounts(symbol,count)
            except (OSError,TimeoutError,ValueError,KeyError,TypeError,ArithmeticError):amounts={}
        now=datetime.now(TZ);rows=[]
        for row in raw[-count:]:
            stamp=str(row[0])
            if period!='day':stamp=datetime.strptime(stamp,'%Y%m%d%H%M').strftime('%Y-%m-%d %H:%M')
            close_at=bar_close_time(stamp,period,symbol)
            closed=close_at<=now
            product=product_meta(symbol)
            amount=amounts.get(stamp) if period=='day' else None
            rows.append(dict(time=stamp,open=num(row[1]),close=num(row[2]),high=num(row[3]),low=num(row[4]),
                volume=None,amount=amount,closed=closed,adjustment=adjustment,
                currency=product['currency'],closed_at=close_at.isoformat(),timezone=product['timezone'],
                precision=len(str(row[2]).partition('.')[2]),volume_unit=None,
                amount_unit='CNY' if amount is not None else None))
        complete=bool(period=='day' and rows and all(r['amount'] is not None for r in rows))
        return dataset('kline',rows,'腾讯网页K线+东财成交额' if complete else '腾讯网页K线',
            status='ok' if complete else 'partial',
            reason=None if complete else '成交量量纲/成交额未核；部分产品日价精度降级',
            symbol=symbol,period=period,adjustment=adjustment,timezone=product['timezone'],
            currency=product['currency'],calendar_verified=product['calendar_verified'],
            precision=min(r['precision'] for r in rows),volume_unit=None,
            amount_unit='CNY' if complete else None)
    raise ValueError('不支持的数据类型')
