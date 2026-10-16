"""行情字段、单位与观察时点的唯一解释；不猜测缺失成交额。"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation

TZ = timezone(timedelta(hours=8))
COLUMNS = ['time', 'open', 'close', 'high', 'low', 'volume']


def instant(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('研究时点必须含时区')
    return result.astimezone(TZ)


def normalize_bar(row: list, columns: list[str]) -> dict:
    if len(row) < len(columns) or len(set(columns)) != len(columns):
        raise ValueError('K线字段缺失或重复')
    result = dict(zip(columns, row))
    if not all(k in result for k in ('time', 'open', 'high', 'low', 'close')):
        raise ValueError('K线缺少必需价格字段')
    for k in ('open', 'high', 'low', 'close', 'volume', 'amount'):
        value = result.get(k)
        if value is None:
            result[k] = None
            continue
        try:
            num = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError('K线非数字') from exc
        if not num.is_finite() or num < 0 or (k in ('open','high','low','close') and num == 0):
            raise ValueError('K线数值无效')
        result[k] = str(num)
    o, h, l, c = (Decimal(result[k]) for k in ('open', 'high', 'low', 'close'))
    if h < max(o, c, l) or l > min(o, c):
        raise ValueError('OHLC高低关系无效')
    return result


def normalize_series(meta: dict, as_of: str) -> list[dict]:
    cutoff = instant(as_of)
    if meta.get('normalized'):
        # 与网页读取同一规范化段，不从前端字段或另一个来源重新解释量纲。
        rows = meta['normalized']['data']
        return sorted((dict(row) for row in rows if row.get('closed') and
            datetime.combine(datetime.fromisoformat(row['time']).date(),datetime.min.time(),TZ).replace(hour=15)<=cutoff),
            key=lambda b:b['time'])
    retrieved = instant(meta['updated_at']) if meta.get('updated_at') else None
    result = []
    for row in meta.get('bars', []):
        bar = normalize_bar(row, meta.get('columns', COLUMNS))
        date = datetime.fromisoformat(bar['time']).date()
        close = datetime.combine(date, datetime.min.time(), TZ).replace(hour=15)
        complete = retrieved is not None and retrieved >= close and cutoff >= close
        if complete:
            bar.update(closed=True, amount_unit=meta.get('amount_unit'), volume_unit=meta.get('volume_unit'),
                       adjustment=meta.get('adjustment', 'unknown'))
            result.append(bar)
    result.sort(key=lambda b: b['time'])
    if len({b['time'] for b in result}) != len(result):
        raise ValueError('重复K线时间')
    return result


def validate_snapshot(snapshot: dict, as_of: str) -> list[dict]:
    cutoff, issues = instant(as_of), []
    for key, quote in snapshot.get('quotes', {}).items():
        market_time = quote.get('market_time')
        requested = quote.get('requested_at')
        if not market_time:
            issues.append({'symbol': key, 'code': 'quote_time_unknown', 'severity': 'warning'})
        for field, value in [('market_time', market_time), ('requested_at', requested)]:
            if value:
                try:
                    dt = instant(value)
                    if dt > cutoff:
                        issues.append({'symbol': key, 'code': 'future_quote', 'severity': 'blocking', 'field': field})
                    elif (cutoff - dt).total_seconds() > 1800:
                        issues.append({'symbol': key, 'code': 'stale_quote', 'severity': 'blocking', 'field': field})
                except ValueError:
                    issues.append({'symbol': key, 'code': 'invalid_time', 'severity': 'blocking', 'field': field})
    return issues
