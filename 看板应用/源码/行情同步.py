#!/usr/bin/env python3
"""只读行情兼容层：报价快照与K线合并；绝不查询比赛账户或提交委托。

实际采集由`市场同步`完成（华泰优先、公开源补充）；保留台账命令与测试稳定入口。
"""
from decimal import Decimal, InvalidOperation

import 账户核心 as core

# 港股持仓折算率：人民币/港币，与股票报价同批缓存。
HK_RATE = 'FX:HKDCNY'

KLINE_SOURCES = {
    'm5': 'https://ifzq.gtimg.cn/appstock/app/kline/mkline?param={symbol},m5,,{count}',
    'm15': 'https://ifzq.gtimg.cn/appstock/app/kline/mkline?param={symbol},m15,,{count}',
    'm30': 'https://ifzq.gtimg.cn/appstock/app/kline/mkline?param={symbol},m30,,{count}',
    'm60': 'https://ifzq.gtimg.cn/appstock/app/kline/mkline?param={symbol},m60,,{count}',
    'day': 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{count},qfq'
}
QUOTE_FIELDS = (('prevClose', 'prev_close'), ('limitUp', 'limit_up'), ('limitDown', 'limit_down'),
                ('bidPrice1', 'bid1'), ('askPrice1', 'ask1'))


def quote_snapshot(payload):
    snapshot = {'price': str(core.number(payload['currentPrice'], positive=True))}
    for source, target in QUOTE_FIELDS:
        value = payload.get(source)
        try:
            snapshot[target] = str(core.number(value)) if value is not None else None
        except (InvalidOperation, TypeError, ValueError):
            snapshot[target] = None
    try:
        snapshot['change_pct'] = core.pct(Decimal(str(payload['change']))) if payload.get('change') is not None else None
    except (InvalidOperation, TypeError, ValueError):
        snapshot['change_pct'] = None
    snapshot['suspended'] = bool(payload.get('isSuspended'))
    return snapshot


def fetch_quotes(positions):
    """共享报价路由转旧账户字段；无华泰认证时保留公开补充源。"""
    from 数据源.公共行情 import fetch_quotes as fetch_public
    keys = [p['key'] for p in positions]
    # 港股持仓需要人民币折算率：与股票报价同批取回并写入缓存。
    if any(p.get('exchange') == 'HK' for p in positions):
        keys.append(HK_RATE)
    rows = fetch_public(keys)
    stamp = core.now()
    updates = {key: dict(q, requested_at=stamp, market_time=q.get('source_as_of'),
        normalized_quote=q, change_pct=str(Decimal(q['change_pct'])*100) if q.get('change_pct') is not None else None)
        for key, q in rows.items()}
    return updates, [{'symbol':key,'category':'missing'} for key in keys if key not in updates]

def refresh(path=core.DEFAULT):
    account, cache = core.load_account(path), core.load_cache(path)
    positions = core.calculate(account, cache.get('quotes', {}))['positions']
    if positions:
        updates, errors = fetch_quotes(positions)
    else:
        updates, errors = {}, []
    with core.lock(path):
        account, cache = core.load_account(path), core.load_cache(path)
        current_symbols = {position['key'] for position in core.calculate(account, cache.get('quotes', {}))['positions']}
        wanted = set(current_symbols) | ({HK_RATE} if any(key.startswith('HK:') for key in current_symbols) else set())
        cache.setdefault('quotes', {}).update({key: value for key, value in updates.items() if key in wanted})
        cache['last_quote_attempt'], cache['quote_errors'] = core.now(), errors
        core.save_cache(path, cache)
        event = '空仓估值' if not current_symbols else ('行情估值' if not errors else '行情部分更新/失败（沿用旧值）')
        nav = core.load_nav(path)
        observations = nav.get('observations', [])
        force = bool(current_symbols) or not observations or observations[-1].get('event') != '空仓估值'
        summary = core.append_observation(path, event, account, cache, force=force)
    return {'报价失败': errors, '持仓报价': {position['key']: {
        'price': position['price'], 'change_pct': position['change_pct'], 'quote_state': position['quote_state']
    } for position in summary['positions']}, '报价时间': cache['last_quote_attempt']}


def merge_bars(stored, fresh, keep):
    merged, added = {bar[0]: bar for bar in stored}, 0
    for bar in fresh:
        if bar[0] not in merged:
            added += 1
        merged[bar[0]] = bar
    return [merged[key] for key in sorted(merged)][-keep:], added


def sync(path=core.DEFAULT, granularities=('m5', 'day'), use_quote=True):
    """兼容旧研究/CLI入口，使用看板相同的批量采集与规范化缓存。"""
    import 市场同步
    sections = None if use_quote else ('kline',)
    return 市场同步.sync(path, sections, False)
