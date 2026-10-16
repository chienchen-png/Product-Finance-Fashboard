"""纯函数：价格描述、真实成交额和历史组合风险。比例均为小数。"""
from math import sqrt, isfinite
from statistics import mean, median, stdev, covariance

from 研究.数据 import instant
from 数据契约 import TZ
from datetime import datetime


def _result(value, count, cutoff, unit='ratio', reason=None):
    return {'value': value, 'status': 'ok' if value is not None else 'missing',
            'sample_count': count, 'cutoff': cutoff, 'unit': unit, 'reason': reason}


def compute_indicators(bars: list[dict], benchmark: list[dict], as_of: str) -> dict:
    day = instant(as_of).date().isoformat()
    rows = sorted((b for b in bars if b.get('closed') and b['time'][:10] <= day), key=lambda b:b['time'])
    closes = [float(b['close']) for b in rows]
    if any(not isfinite(c) or c <= 0 for c in closes):
        raise ValueError('无效收盘价')
    if len({b['time'] for b in rows}) != len(rows):
        raise ValueError('重复日线')
    cutoff = rows[-1]['time'] if rows else None
    out = {}
    for n in (5, 20):
        out['return'+str(n)] = _result(closes[-1]/closes[-n-1]-1 if len(rows)>n else None,
                                      min(len(rows), n+1), cutoff, reason=None if len(rows)>n else '收盘端点不足')
    out['ma20'] = _result(mean(closes[-20:]) if len(rows)>=20 else None, min(len(rows),20), cutoff, 'price')
    tr = [max(float(b['high'])-float(b['low']), abs(float(b['high'])-closes[i-1]),
              abs(float(b['low'])-closes[i-1])) for i,b in enumerate(rows) if i>0]
    out['atr14'] = _result(mean(tr[-14:]) if len(tr)>=14 else None, min(len(tr),14), cutoff, 'price')
    returns = [closes[i]/closes[i-1]-1 for i in range(1,len(closes))]
    for n in (20,60):
        out['vol'+str(n)] = _result(stdev(returns[-n:])*sqrt(252) if len(returns)>=n else None,
                                    min(len(returns),n), cutoff)
    amounts = [float(b['amount']) for b in rows[-20:] if b.get('amount') is not None and b.get('amount_unit')=='CNY']
    out['turnover20'] = _result(median(amounts) if len(amounts)==20 else None, len(amounts), cutoff, 'CNY',
                                '需20个真实成交额及CNY单位' if len(amounts)<20 else None)
    base = {b['time']:float(b['close']) for b in benchmark if b.get('closed') and b['time'][:10]<=day}
    own = {b['time']:float(b['close']) for b in rows}
    common = sorted(set(base)&set(own))
    enough = len(common)>=21 and common[-1]==cutoff and common[-1]==max(base)
    rs = (own[common[-1]]/own[common[-21]] - base[common[-1]]/base[common[-21]]) if enough else None
    out['rs20'] = _result(rs, min(len(common),21), common[-1] if common else None)
    return out


def portfolio_risk(returns: dict, weights: dict) -> dict:
    keys = [key for key,value in weights.items() if value != 0]
    if not keys:
        return _result(0.0, 0, None)
    if any(key not in returns or not returns[key] for key in keys):
        return _result(None, 0, None, reason='组合风险序列缺失')
    common = sorted(set.intersection(*(set(returns[k]) for k in keys)))
    if len(common)<60:
        return _result(None, len(common), common[-1] if common else None, reason='需60个共同日收益，即至少61个收盘端点')
    out = _result(0.0, 60, common[-1])
    vols = []
    for n in (20,60):
        series = [[float(returns[k][d]) for d in common[-n:]] for k in keys]
        if any(not isfinite(v) for s in series for v in s):
            raise ValueError('风险序列含非有限数')
        cov = [[covariance(a,b) for b in series] for a in series]
        variance = sum(float(weights[a])*float(weights[b])*cov[i][j]
                       for i,a in enumerate(keys) for j,b in enumerate(keys))
        vol = sqrt(max(0,252*variance))
        out['covariance'+str(n)] = {'symbols':keys,'matrix':cov}
        out['vol'+str(n)] = vol
        vols.append(vol)
    out['value'] = max(vols)
    return out

ALGORITHM_VERSION = '1.0'


def _ema(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    out[period-1] = mean(values[:period])
    alpha = 2/(period+1)
    for i in range(period,len(values)):
        out[i] = values[i]*alpha + out[i-1]*(1-alpha)
    return out


def technical_series(bars: list[dict], as_of: str) -> dict:
    cutoff = instant(as_of)
    rows = []
    for bar in bars:
        if not bar.get('closed'):
            continue
        when = datetime.fromisoformat(bar.get('closed_at') or bar['time'])
        if when.tzinfo is None:when=when.replace(tzinfo=TZ)
        if len(bar['time']) == 10 and not bar.get('closed_at'):
            when = when.replace(hour=15)
        if when <= cutoff:
            rows.append(bar)
    rows.sort(key=lambda b:b['time'])
    if len({r['time'] for r in rows}) != len(rows):
        raise ValueError('重复K线时间')
    closes = [float(b['close']) for b in rows]
    if any(not isfinite(c) or c<=0 for c in closes):
        raise ValueError('无效价格')
    n = len(rows)
    series = {}
    required = {'ma5':5,'ma10':10,'ma20':20,'ma60':60,'macd_dif':26,
                'macd_dea':34,'macd_hist':34,'rsi14':15}
    for length in (5,10,20,60):
        series['ma'+str(length)] = [mean(closes[i-length+1:i+1]) if i>=length-1 else None for i in range(n)]
    fast,slow = _ema(closes,12),_ema(closes,26)
    dif = [fast[i]-slow[i] if slow[i] is not None else None for i in range(n)]
    valid = [v for v in dif if v is not None]
    signal = _ema(valid,9)
    dea = [None]*min(n,25)+signal
    series.update(macd_dif=dif,macd_dea=dea,
                  macd_hist=[2*(a-b) if a is not None and b is not None else None for a,b in zip(dif,dea)])
    rsi = [None]*n
    if n>=15:
        changes = [closes[i]-closes[i-1] for i in range(1,n)]
        up = mean(max(v,0) for v in changes[:14])
        down = mean(max(-v,0) for v in changes[:14])
        def value(gain,loss):
            return 50.0 if gain==loss==0 else 100.0 if loss==0 else 100-100/(1+gain/loss)
        rsi[14] = value(up,down)
        for i in range(15,n):
            up = (up*13+max(changes[i-1],0))/14
            down = (down*13+max(-changes[i-1],0))/14
            rsi[i] = value(up,down)
    series['rsi14'] = rsi
    last = rows[-1]['time'] if rows else None
    summary = {key:dict(value=values[-1] if values else None,
        status='ok' if n>=required[key] else 'missing',required_samples=required[key],
        sample_count=n,cutoff=last) for key,values in series.items()}
    return dict(algorithm_version=ALGORITHM_VERSION,cutoff=last,sample_count=n,
                times=[b['time'] for b in rows],series=series,summary=summary)


def chart_series(entry: dict, as_of: str, symbol=None) -> dict:
    """给旧/新K线段附加相同后端指标；不写缓存、不取行情。"""
    output = dict(entry)
    for period,meta in entry.items():
        if not isinstance(meta,dict) or 'bars' not in meta:
            continue
        if symbol:
            from 数据契约 import normalize_cached_series
            meta=normalize_cached_series(symbol,meta,instant(as_of))
        try:
            rows = (meta.get('normalized') or {}).get('data')
            if rows is None:
                cols = meta.get('columns',['time','open','close','high','low','volume'])
                rows = []
                for raw in meta['bars']:
                    row = dict(zip(cols,raw))
                    stamp = datetime.fromisoformat(row['time']).replace(tzinfo=TZ)
                    if len(row['time'])==10: stamp=stamp.replace(hour=15)
                    row.update(closed=stamp<=instant(as_of),amount_unit=meta.get('amount_unit'))
                    rows.append(row)
            technical = technical_series(rows,as_of)
            extras = compute_indicators(rows,[],as_of) if period.startswith('day') else {}
            output[period] = dict(meta,technical=technical,indicators=extras)
        except (ValueError,KeyError,TypeError,ArithmeticError):
            output[period] = dict(meta,technical=None,indicator_error='指标输入缺失或无效')
    return output
