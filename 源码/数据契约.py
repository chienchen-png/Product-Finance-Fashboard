"""共享数据契约；不访问网络、文件或账户。比例统一小数，金额为十进制字符串。"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import copy
from zoneinfo import ZoneInfo

TZ = timezone(timedelta(hours=8))
STATUSES = {'ok', 'stale', 'partial', 'unavailable', 'unknown'}
PERIODS = {'day', 'm5'}


def product_meta(symbol):
    validate_symbol(symbol)
    if symbol.startswith('HK:') or symbol in ('INDEX:HSI','INDEX:HSTECH'):
        return dict(timezone='Asia/Hong_Kong',currency='HKD',close_hour=16,calendar_verified=False)
    if symbol in ('INDEX:NDX','INDEX:INX'):
        return dict(timezone='America/New_York',currency='USD',close_hour=16,calendar_verified=False)
    return dict(timezone='Asia/Shanghai',currency='USD' if symbol=='FUT:GC' else 'CNY',close_hour=15,
                calendar_verified=symbol.startswith(('SH:','SZ:','BJ:')))


def bar_close_time(stamp, period, symbol):
    meta=product_meta(symbol)
    value=datetime.fromisoformat(stamp).replace(tzinfo=ZoneInfo(meta['timezone']))
    return value.replace(hour=meta['close_hour'],minute=0,second=0) if period=='day' else value


def normalize_cached_series(symbol, meta, now):
    """升级旧派生缓存的市场口径；不改变任何价量和来源时间。"""
    product=product_meta(symbol);out=copy.deepcopy(meta)
    out.update(currency=product['currency'],timezone=product['timezone'])
    ds=out.get('normalized')
    if ds and ds.get('period') in ('day','m5'):
        ds.update(currency=product['currency'],timezone=product['timezone'],calendar_verified=product['calendar_verified'])
        for row in ds.get('data',[]):
            end=bar_close_time(row['time'],ds['period'],symbol)
            row.update(currency=product['currency'],timezone=product['timezone'],closed_at=end.isoformat(),closed=end<=now)
    return out


def instant(value):
    result = datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        raise ValueError('时间必须包含时区')
    return result


def validate_symbol(symbol):
    if not isinstance(symbol, str) or not re.fullmatch(
            r'(?:(?:SH|SZ|BJ):\d{6}|HK:\d{5}|INDEX:[A-Z0-9]{2,12}|FX:[A-Z]{6}|FUT:[A-Z]{2,8})', symbol):
        raise ValueError('无效产品标识')
    return symbol


# 代码长度与前缀唯一确定交易所：5位港股通，6位沪深北。录入只需代码。
PREFIX_EXCHANGE = (('SH', '56'), ('SZ', '013'), ('BJ', '489'))


def exchange_of(code, exchange=None):
    text = str(code or '').strip()
    if re.fullmatch(r'\d{5}', text):
        derived = 'HK'
    elif re.fullmatch(r'\d{6}', text):
        derived = next((name for name, prefixes in PREFIX_EXCHANGE if text[0] in prefixes), None)
        if not derived:
            raise ValueError('无法按代码判断交易所，请在“更多”中选择')
    else:
        raise ValueError('股票代码须为5位港股或6位沪深北代码')
    given = str(exchange or '').strip().upper()
    if given and given != derived:
        raise ValueError(f'交易所与代码前缀不符：{text} 应为 {derived}')
    return derived


def decimal_text(value, *, positive=False):
    if value is None or value in ('', '-', '--'):
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('非数值字段') from exc
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError('无效数值')
    return format(result, 'f')


def ratio(value):
    text = decimal_text(value)
    return decimal_text(Decimal(text) / 100) if text is not None else None


def revision(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def dataset(kind, data, source, *, source_as_of=None, source_time_kind='provider_update',
            timezone='Asia/Shanghai', status='ok', reason=None, coverage=None, retrieved_at=None, **extra):
    out = dict(schema_version=1, kind=kind, source=source, source_as_of=source_as_of,
        source_time_kind=source_time_kind if source_as_of else 'unknown',
        retrieved_at=retrieved_at or datetime.now(TZ).isoformat(timespec='seconds'),
        timezone=timezone, status=status, reason=reason, coverage=coverage or {}, data=data, **extra)
    out['revision'] = revision(out)
    return validate_dataset(out)


def validate_dataset(raw):
    required = {'schema_version','kind','revision','source','source_as_of','source_time_kind',
                'retrieved_at','timezone','status','reason','coverage','data'}
    if not isinstance(raw, dict) or not required <= raw.keys() or raw['status'] not in STATUSES:
        raise ValueError('数据集契约不符')
    instant(raw['retrieved_at'])
    if raw['source_as_of']:
        instant(raw['source_as_of'])
    revision(raw)  # 拒绝非JSON值和NaN/Infinity。
    return raw


def freshness(ds, now, market_state):
    status = ds.get('status', 'unknown')
    if status in ('unavailable', 'partial', 'stale'):
        return status
    if not ds.get('source_as_of'):
        return 'unknown'
    try:
        as_of = instant(ds['source_as_of'])
        if as_of > now + timedelta(minutes=2):
            return 'unknown'
        if market_state == 'closed' and as_of.date() == now.astimezone(as_of.tzinfo).date() and as_of.hour>=ds.get('session_close_hour',15):
            return 'ok'
        # 不在此猜海外节假日。调用方可传 last_session 日期校验后的 closed 状态。
        if market_state == 'closed' and ds.get('last_session') == as_of.date().isoformat() and as_of.hour>=ds.get('session_close_hour',15):
            return 'ok'
        return 'ok' if (now-as_of).total_seconds() <= ds.get('max_age_seconds',1800) else 'stale'
    except (ValueError, TypeError):
        return 'unknown'


def merge_series(previous, incoming, keep):
    """切换来源/复权/量纲时整段替换，禁止把不同口径拼成同一序列。"""
    keys = ('source','adjustment','volume_unit','amount_unit','precision')
    same = previous and all(previous.get(k) == incoming.get(k) for k in keys)
    rows = {row['time']:row for row in (previous.get('data',[]) if same else [])}
    rows.update({row['time']:row for row in incoming['data']})
    result = dict(incoming, data=[rows[k] for k in sorted(rows)][-keep:])
    result['revision'] = revision(result['data'])
    return result
