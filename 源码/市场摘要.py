"""已缓存行情的确定性统计；无网络、账户写入或全市场推断。"""
from datetime import datetime
from decimal import Decimal,InvalidOperation
from statistics import median
from 数据契约 import dataset, decimal_text


def number(value):
    try:
        if value is None or isinstance(value,bool):return None
        v=Decimal(str(value))
        return v if v.is_finite() else None
    except (InvalidOperation,ValueError,TypeError):return None


def amount_day(row):
    source=row.get('source_fields',{}).get('amount',row.get('source'))
    stamp=row.get('source_as_of') if source==row.get('source') else None
    ref=row.get('reference_quote') or {}
    if not stamp and source==ref.get('source'):stamp=ref.get('source_as_of')
    try:return datetime.fromisoformat(stamp).date().isoformat() if stamp else None
    except (ValueError,TypeError):return None


def build(overview,sectors,series):
    quotes={r['symbol']:r for r in overview.get('data',[])}
    out=[];parts=[quotes.get(s,{}) for s in ('SH:000001','SZ:399001')]
    days=[amount_day(r) for r in parts]
    if all(number(r.get('amount')) is not None and number(r.get('amount'))>=0 and r.get('amount_unit')=='CNY' for r in parts) and days[0] and days[0]==days[1]:
        out.append(dict(id='amount',label='沪深成交额',value=decimal_text(sum(Decimal(str(r['amount'])) for r in parts)),unit='CNY',date=days[0],scope='沪市＋深市，不重复加创业板',status='unknown' if any(r.get('status')=='unknown' for r in parts) else overview['status']))
    values=[v for r in sectors.get('data',[]) if (v:=number(r.get('change_pct'))) is not None]
    if values:
        common=dict(status=sectors['status'],source_as_of=sectors.get('source_as_of'),coverage=len(values),total=len(sectors.get('data',[])),scope=sectors.get('coverage',{}).get('scope','已覆盖行业，非全A股票'))
        out += [dict(id='breadth',label='覆盖行业涨 / 跌 / 平',up=sum(v>0 for v in values),down=sum(v<0 for v in values),flat=sum(v==0 for v in values),**common),
                dict(id='median',label='行业涨跌中位数',value=decimal_text(median(values)),unit='ratio',**common)]
    trends={}
    for symbol,row in quotes.items():
        if row.get('product_type')!='index':continue
        meta=series.get(symbol,{}).get('day',{})
        normalized=meta.get('normalized') or {}
        if normalized.get('data'):
            bars=[b for b in normalized['data'] if b.get('closed')]
            closes=[number(b.get('close')) for b in bars]
            cutoff=bars[-1]['time'] if bars else None
        else:
            cols=meta.get('columns',['time','open','close','high','low','volume']);bars=[]
            for b in meta.get('bars',[]):
                v=dict(zip(cols,b))
                try:
                    # 旧缓存没有收线契约时，保守排除取数当日；不把盘中收盘价当日收线。
                    if v['time'][:10] < str(meta.get('updated_at',''))[:10]:bars.append(v)
                except (KeyError,TypeError):pass
            closes=[number(b.get('close')) for b in bars];cutoff=bars[-1]['time'] if bars else None
        if len(closes)>=21 and all(v is not None and v>0 for v in closes[-21:]):
            trends[symbol]=dict(return20=decimal_text(closes[-1]/closes[-21]-1),cutoff=cutoff,source=meta.get('source'),adjustment=meta.get('adjustment'))
    return dataset('summary',out,'本机缓存计算',retrieved_at=overview.get('retrieved_at'),status='unknown' if not out or any(r.get('status')!='ok' for r in out) else 'ok',coverage={'scope':'仅已覆盖行情与行业','trends':trends})
