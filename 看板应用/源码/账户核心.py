#!/usr/bin/env python3
"""比赛账户的账务计算、分层存储与看板读模型。"""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
import json
import hashlib
import os
from pathlib import Path
import shutil
import tempfile

import 路径
from 数据契约 import revision as account_revision, freshness

ROOT = 路径.数据根()
DEFAULT = ROOT / '账户记录/比赛账户.json'
TZ = timezone(timedelta(hours=8))
QUOTE_TTL_SECONDS = 30 * 60


def now():
    return datetime.now(TZ).isoformat(timespec='seconds')


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return parsed.astimezone(TZ).isoformat(timespec='seconds')


def number(value, positive=False):
    result = Decimal(str(value))
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError('金额或价格必须为有限非负数，成交价格必须大于0')
    return result


def money(value):
    if value is None:
        return None
    return format(value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP), 'f')


def pct(value):
    if value is None:
        return None
    return format(value.quantize(Decimal('.0001'), rounding=ROUND_HALF_UP), 'f')


def cache_path(path=DEFAULT):
    return Path(path).with_name('行情缓存.json')


def nav_path(path=DEFAULT):
    return Path(path).with_name('收益曲线.json')


def legacy_kline_path(path=DEFAULT):
    return Path(path).with_name('行情K线.json')


@contextmanager
def lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = path.with_suffix('.lock')
    try:
        fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError('台账正由另一任务写入；确认无进程后再处理遗留.lock') from exc
    try:
        os.close(fd)
        yield
    finally:
        lock_file.unlink(missing_ok=True)


def atomic_text(path, body):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(body)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def write_json(path, data):
    atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def read_json(path, default=None):
    path = Path(path)
    if not path.exists() and default is not None:
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise ValueError(path.name + '损坏或不可读，已停止覆盖') from exc


def _confirmation(trade):
    note = str(trade.get('note', ''))
    return {
        'execution': 'confirmed',
        'time': 'inferred' if '暂记' in note else 'confirmed',
        'fee': 'unknown' if trade.get('fee') is None else ('inferred' if '反推' in note else 'confirmed')
}


def migrate(path=DEFAULT):
    """把v1混合文件迁移为事实、行情、收益三层；迁移前材料完整归档。"""
    path = Path(path)
    raw = read_json(path)
    if raw.get('version') == 2 and not any(key in raw for key in ('quotes', 'summary', 'snapshots')):
        return False
    stamp = datetime.now(TZ).strftime('%Y%m%d_%H%M%S')
    archive = path.parent / '历史归档'
    archive.mkdir(parents=True, exist_ok=True)
    backup = archive / f'{path.stem}_v1_迁移前_{stamp}.json'
    shutil.copy2(path, backup)

    legacy_kline = legacy_kline_path(path)
    old_kline = read_json(legacy_kline, {'version': 1, 'series': {}})
    if legacy_kline.exists():
        shutil.copy2(legacy_kline, archive / f'{legacy_kline.stem}_v1_迁移前_{stamp}.json')

    facts = {key: raw[key] for key in ('account', 'currency', 'initial_cash', 'started_at', 'baseline_source')}
    facts.update({
        'version': 2,
        'facts_updated_at': raw.get('updated_at') or now(),
        'trades': raw.get('trades', []),
        'pending_orders': raw.get('pending_orders', []),
        'corrections': raw.get('corrections', [])
})
    for trade in facts['trades']:
        trade.setdefault('confirmation', _confirmation(trade))
    market = {
        'version': 2,
        'updated_at': old_kline.get('updated_at') or raw.get('last_quote_attempt'),
        'last_quote_attempt': raw.get('last_quote_attempt'),
        'quote_errors': raw.get('quote_errors', []),
        'quotes': raw.get('quotes', {}),
        'series': old_kline.get('series', {})
}
    nav = {'version': 2, 'updated_at': raw.get('updated_at'), 'observations': raw.get('snapshots', [])}
    previous = path.with_suffix('.json.bak')
    if path.exists():
        shutil.copy2(path, previous)
    write_json(path, facts)
    write_json(cache_path(path), market)
    write_json(nav_path(path), nav)
    if legacy_kline.exists():
        legacy_kline.unlink()
    return True


def load_account(path=DEFAULT):
    path = Path(path)
    raw = read_json(path)
    if raw.get('version') != 2 or any(key in raw for key in ('quotes', 'summary', 'snapshots')):
        raise ValueError('旧账户格式，请显式运行migrate后再读取')
    return raw


def load_cache(path=DEFAULT):
    load_account(path)
    target = cache_path(path)
    try:
        return read_json(target, empty_cache())
    except ValueError:
        # GET/CLI读取无写入；错误交由后台采集任务报告并重建。
        return empty_cache()


def empty_cache():
    return {'version': 2, 'updated_at': None, 'last_quote_attempt': None,
            'quote_errors': [], 'quotes': {}, 'series': {}}


def load_nav(path=DEFAULT):
    load_account(path)
    return read_json(nav_path(path), {'version': 2, 'updated_at': None, 'observations': []})


def save_account(path, data):
    path = Path(path)
    data['version'] = 2
    data['facts_updated_at'] = now()
    write_json(path, data)


def save_cache(path, data):
    data['version'] = 2
    data['updated_at'] = now()
    write_json(cache_path(path), data)


def save_nav(path, data):
    data['version'] = 2
    data['updated_at'] = now()
    write_json(nav_path(path), data)


def invalidate_observations(path, since, reason):
    """事实变更使其后旧估值失效；原数值保留，初始资金基线不删除。"""
    nav=load_nav(path)
    changed=False
    for point in nav.get('observations',[]):
        if point.get('event')!='初始资金' and point.get('time','')>=since:
            point['valid']=False
            point['invalid_reason']=reason
            changed=True
    if changed:save_nav(path,nav)


def trade_digest(trades):
    return hashlib.sha256(json.dumps(trades, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def hk_rate(account, quotes=None):
    """人民币/港币折算率：优先缓存实时汇率，其次最近一笔港股成交汇率；都无则None。"""
    quote = (quotes or {}).get('FX:HKDCNY') or {}
    value = quote.get('price')
    if value not in (None, ''):
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            pass
    for trade in reversed(account.get('trades', [])):
        if trade.get('exchange') == 'HK' and trade.get('fx'):
            try:
                return Decimal(str(trade['fx']))
            except (InvalidOperation, TypeError, ValueError):
                return None
    return None


def trade_rate(trade):
    """成交折算率：港股按成交时汇率换人民币，其他市场为1；缺汇率的港股成交记为未知。"""
    if trade.get('exchange') != 'HK':
        return Decimal(1)
    if not trade.get('fx'):
        return None
    try:
        return Decimal(str(trade['fx']))
    except (InvalidOperation, TypeError, ValueError):
        return None


def calculate(account, quotes=None, at=None):
    """按已登记的因果顺序计算；未知成交字段只影响依赖它的金额。"""
    quotes = quotes or {}
    instant = at or datetime.now(TZ)
    hk_now = hk_rate(account, quotes)
    initial = number(account['initial_cash'], positive=True)
    cash, realized = initial, Decimal(0)
    holdings, unknown_fees, missing, seen = {}, [], [], set()
    historical_missing, cost_adjustment = [], Decimal(0)
    trades = account.get('trades', [])
    reports = [r for r in account.get('reconciliations', [])
               if datetime.fromisoformat(r['recorded_at']) <= instant]
    report = reports[-1] if reports else None
    if report and trade_digest(trades[:report['covered_trade_count']]) != report['trade_basis']:
        report = None  # 覆盖范围内事实已变，旧对账基线不能继续使用。
    def anchor():
        nonlocal cash, realized, holdings, missing, historical_missing, cost_adjustment
        cash = Decimal(report['summary']['available_cash'])
        realized = None  # 手机未报告已实现盈亏；不同费用口径的汇总差值不能代替它。
        holdings = {}
        for p in report['positions']:
            rate = (Decimal(p['fx']) if p.get('fx') else hk_now) if p['exchange'] == 'HK' else Decimal(1)
            holdings[p['key']] = dict(p, cost=(Decimal(p['average_cost']) * p['quantity'] * rate
                                               if rate is not None else None),
                cost_hkd=(Decimal(p['average_cost']) * p['quantity'] if p['exchange'] == 'HK' else None),
                last_price=p['price'], last_trade_time=report['recorded_at'],
                last_price_source='用户手机回报（行情时点未提供）', cost_basis='手机显示均价，逐项盈亏为估算')
        reported_profit = report['summary'].get('unrealized_profit')
        cost_adjustment = (Decimal(report['summary']['market_value']) - Decimal(reported_profit)
                           - sum(h['cost'] for h in holdings.values())) if reported_profit is not None else None
        historical_missing, missing = list(missing), []
    if report and report['covered_trade_count'] == 0:
        anchor()
    def add(a, b):
        return None if a is None or b is None else a + b
    def decimal(value):
        return None if value is None else Decimal(str(value))
    for index, trade in enumerate(trades):
        if trade['id'] in seen:
            raise ValueError('重复成交id')
        seen.add(trade['id'])
        if trade.get('time') and trade['time'] < account['started_at']:
            raise ValueError('成交时间早于建账基线')
        if report and index >= report['covered_trade_count'] and trade.get('time') and trade['time'] < (report.get('reported_at') or report['recorded_at']):
            raise ValueError('成交早于当前手机快照，已包含在基线中，不能再次补记')
        key = trade['exchange'] + ':' + trade['code']
        holding = holdings.setdefault(key, {'code': trade['code'], 'exchange': trade['exchange'],
                                            'name': trade['name'], 'quantity': 0, 'cost': Decimal(0)})
        amount, fee = decimal(trade.get('amount')), decimal(trade.get('fee'))
        native_cost, native_proceeds = add(amount, fee), add(amount, -fee if fee is not None else None)
        rate = trade_rate(trade)
        if rate != Decimal(1):
            # 港股成交按成交时汇率折成人民币入账；缺汇率时金额与费用按未知处理。
            amount = amount * rate if amount is not None and rate is not None else None
            fee = fee * rate if fee is not None and rate is not None else None
        if fee is None:
            unknown_fees.append(trade['id'])
        for field in ('price', 'fee', 'time'):
            if trade.get(field) is None:
                missing.append({'trade_id': trade['id'], 'field': field})
        if trade['side'] == 'buy':
            cost = add(amount, fee)
            cash = add(cash, -cost if cost is not None else None)
            holding['cost'] = add(holding['cost'], cost)
            if holding['exchange'] == 'HK':
                # 港币成本单独留一份，持仓均价按港币显示，不随汇率变动。
                holding['cost_hkd'] = add(holding.get('cost_hkd', Decimal(0)), native_cost)
            holding['quantity'] += trade['quantity']
        else:
            if holding['quantity'] < trade['quantity']:
                raise ValueError('卖出数量超过此前已确认持仓')
            removed = holding['cost'] * Decimal(trade['quantity']) / holding['quantity'] if holding['cost'] is not None else None
            holding['cost'] = add(holding['cost'], -removed if removed is not None else None)
            if holding['exchange'] == 'HK' and holding.get('cost_hkd') is not None:
                removed_hkd = holding['cost_hkd'] * Decimal(trade['quantity']) / holding['quantity']
                holding['cost_hkd'] = add(holding['cost_hkd'], -removed_hkd)
            holding['quantity'] -= trade['quantity']
            proceeds = add(amount, -fee if fee is not None else None)
            cash = add(cash, proceeds)
            realized = add(realized, add(proceeds, -removed if removed is not None else None))
            if report and index >= report['covered_trade_count'] and cost_adjustment:
                # 手机总成本与四舍五入的逐项均价有差额，不能臆造卖出部分的费用分配。
                cost_adjustment, realized = None, None
        if cash is not None and cash < 0:
            raise ValueError('成交导致现金为负，请核对成交或费用')
        holding['last_price'] = trade.get('price')
        holding['last_trade_time'] = max(filter(None, (trade.get('time') or trade.get('trade_date'),
            report['recorded_at'] if report and index >= report['covered_trade_count'] else None)), default=None)
        holding['last_price_source'] = '成交价参考（待刷新）'
        if report and index + 1 == report['covered_trade_count']:
            anchor()
    positions, market_value = [], Decimal(0)
    for key, holding in holdings.items():
        quantity = holding['quantity']
        if not quantity:
            continue
        quote = quotes.get(key)
        extras = {'quote_fresh': False, 'quote_state': 'missing', 'quote_age_seconds': None,
                  'change_pct': None, 'prev_close': None, 'limit_up': None, 'limit_down': None,
                  'bid1': None, 'ask1': None, 'suspended': False, 'market_time': None}
        if quote and quote.get('requested_at', '') >= (holding['last_trade_time'] or ''):
            price, price_time = decimal(quote['price']), quote['requested_at']
            source = quote.get('source', '缓存行情')
            from 市场同步 import market_state, session_key
            from 数据契约 import product_meta
            source_time = quote.get('source_as_of') or quote.get('market_time')
            age = None
            if source_time:
                try:age=max(0,int((instant-datetime.fromisoformat(source_time)).total_seconds()))
                except (ValueError,TypeError):source_time=None
            state=freshness(dict(status='ok',source_as_of=source_time,
                last_session=quote.get('last_session') or session_key(key,instant),
                session_close_hour=product_meta(key)['close_hour']),instant,market_state(key,instant))
            extras.update(quote_age_seconds=age,quote_fresh=state=='ok',
                          quote_state='fresh' if state=='ok' else state)
            for field in ('change_pct', 'prev_close', 'limit_up', 'limit_down', 'bid1', 'ask1', 'suspended', 'market_time'):
                extras[field] = quote.get(field)
            extras['market_time']=source_time
        else:
            price, price_time, source = decimal(holding['last_price']), holding['last_trade_time'], holding.get('last_price_source', '成交价参考（待刷新）')
            extras['quote_state'] = 'trade_fallback' if price is not None else 'missing'
        rate = hk_now if holding['exchange'] == 'HK' else Decimal(1)
        value = price * quantity * rate if price is not None and rate is not None else None
        profit = value - holding['cost'] if value is not None and holding['cost'] is not None else None
        average_cost = (pct(holding['cost_hkd'] / quantity) if holding.get('cost_hkd') is not None else
                        (pct(holding['cost'] / quantity) if holding['cost'] is not None else None))
        market_value = add(market_value, value)
        positions.append({'key': key, 'code': holding['code'], 'exchange': holding['exchange'],
                          'name': holding['name'], 'quantity': quantity, 'cost': money(holding['cost']),
                          'available_quantity': (holding.get('available_quantity')
                                                 if isinstance(holding.get('available_quantity'), int)
                                                 and 0 <= holding['available_quantity'] <= quantity else None),
                          'average_cost': average_cost,
                          'currency': 'HKD' if holding['exchange'] == 'HK' else 'CNY',
                          'fx': str(rate) if holding['exchange'] == 'HK' and rate is not None else None,
                          'price': str(price) if price is not None else None,
                          'market_value': money(value), 'profit': money(profit),
                          'return_pct': pct(profit / holding['cost'] * 100) if profit is not None and holding['cost'] else None,
                          'price_time': price_time, 'price_source': source,
                          'cost_basis': holding.get('cost_basis', '已确认成交金额及费用'), **extras})
    row_market_value = market_value
    using_report = bool(report and len(trades) == report['covered_trade_count']
                        and not any(quotes.get(p['key'], {}).get('requested_at', '') >= report['recorded_at'] for p in positions))
    if using_report:
        market_value = Decimal(report['summary']['market_value'])
    total = add(cash, market_value)
    cost_total = Decimal(0)
    for position in positions:
        cost_total = add(cost_total, decimal(position['cost']))
        position['weight_pct'] = pct(Decimal(position['market_value']) / total * 100) if total and position['market_value'] is not None else None
    monetary_missing = any(item['field'] in ('price', 'fee') for item in missing) or market_value is None
    unrealized = add(market_value, -cost_total if cost_total is not None else None)
    unrealized = add(unrealized, -cost_adjustment if cost_adjustment is not None else None)
    reconciliation = None
    daily_profit = None
    if report:
        rs = report['summary']
        reconciliation = {'id':report['id'], 'recorded_at':report['recorded_at'], 'reported_at':report.get('reported_at'),
            'using_reported_totals':using_report, 'reported_summary':rs,
            'reported_row_market_value':report['checks']['row_market_value'],
            'market_value_difference':report['checks']['market_value_difference'],
            'display_cost_difference':report['checks']['display_cost_difference'],
            'current_row_market_value':money(row_market_value),
            'basis':'手机对账基线' if using_report else '手机现金基线＋持仓行情估值'}
        if total is not None and rs.get('daily_profit') is not None and instant.astimezone(TZ).date().isoformat() == report['recorded_at'][:10]:
            daily_profit = money(Decimal(rs['daily_profit']) + total - Decimal(rs['total_assets']))
    hk_quote = (quotes or {}).get('FX:HKDCNY') or {}
    hk = ({'rate': str(hk_now), 'source': hk_quote.get('source'), 'as_of': hk_quote.get('source_as_of'),
           'source_time_kind': hk_quote.get('source_time_kind')}
          if any(p['exchange'] == 'HK' for p in positions) else None)
    return {'cash': money(cash), 'market_value': money(market_value), 'total_assets': money(total),
            'hk_rate': hk,
            'profit': money(total - initial) if total is not None else None,
            'return_pct': pct((total / initial - 1) * 100) if total is not None else None,
            'realized_profit': money(realized),
            'unrealized_profit': money(unrealized), 'daily_profit': daily_profit,
            'positions': positions, 'unknown_fee_ids': unknown_fees, 'missing_fields': missing,
            'quality': 'incomplete' if monetary_missing else ('reconciled' if report else 'confirmed'),
            'provisional': monetary_missing, 'estimates': {},
            'reconciliation': reconciliation, 'historical_missing_fields':historical_missing,
            'trade_count': len(trades), 'historical_symbol_count': len({t['exchange']+':'+t['code'] for t in trades} | set(holdings))}


def append_observation(path, event, account=None, cache=None, force=True):
    account = account or load_account(path)
    cache = cache or load_cache(path)
    nav = load_nav(path)
    summary = calculate(account, cache.get('quotes', {}))
    item = {'time': now(), 'event': event, 'total_assets': summary['total_assets'],
            'return_pct': summary['return_pct'], 'provisional': summary['provisional'],
            'valid': not summary['provisional'],
            'valuation_basis': (summary.get('reconciliation') or {}).get('basis', '持仓行情/成交价暂估，不是赛事官方收益率')}
    observations = nav.setdefault('observations', [])
    if force or not observations or any(observations[-1].get(key) != item[key]
                                        for key in ('event', 'total_assets', 'provisional')):
        observations.append(item)
        del observations[:-5000]
        save_nav(path, nav)
    return summary


def observe_account(path=DEFAULT, force=False):
    """服务后台检测事实变化并维护派生收益；不修改账户或HTML。"""
    with lock(path):
        account, cache, nav = load_account(path), load_cache(path), load_nav(path)
        rev = account_revision(account)
        changed = nav.get('account_revision') != rev
        stamp = now()
        signature = {t['id']: {'digest': account_revision(t),
            'time': t.get('time') or t.get('trade_date') or stamp}
            for t in account.get('trades', [])}
        previous = nav.get('fact_basis', {})
        changed_times = [v['time'] for key in set(signature) | set(previous)
                         if signature.get(key) != previous.get(key)
                         for v in (signature.get(key), previous.get(key)) if v]
        cutoff = min(changed_times, default=account.get('facts_updated_at',stamp))
        if changed:
            for point in nav.get('observations', []):
                if point.get('event') != '初始资金' and point.get('time','') >= cutoff:
                    point.update(valid=False, invalid_reason='账户事实已变化，原值不再用于收益统计')
        summary = calculate(account, cache.get('quotes', {}))
        points = nav.setdefault('observations', [])
        last = points[-1] if points else {}
        elapsed = (datetime.fromisoformat(stamp)-datetime.fromisoformat(last.get('time',stamp))).total_seconds()
        if changed or force or not points or elapsed >= 300:
            points.append({'time':stamp,'event':'账户变更估值' if changed else '行情估值',
                'total_assets':summary['total_assets'],'return_pct':summary['return_pct'],
                'provisional':summary['provisional'],'valid':not summary['provisional'],
                'account_revision':rev,'market_updated_at':cache.get('last_quote_attempt'),
                'valuation_basis':(summary.get('reconciliation') or {}).get('basis','持仓行情/成交价暂估')})
            # 优先保留每天最后一点，其余保留最近采样；总数有界。
            if len(points)>5000:
                daily = {p['time'][:10]:i for i,p in enumerate(points[:-4000])}
                keep = sorted(set(daily.values()))[-999:]
                points[:] = [points[0]]+[points[i] for i in keep if i]+points[-4000:]
            nav.update(account_revision=rev, fact_basis=signature)
            save_nav(path,nav)
        return summary


def view_model(path=DEFAULT, include_kline=False):
    import 市场同步
    account, cache, nav = load_account(path), load_cache(path), load_nav(path)
    summary = calculate(account, cache.get('quotes', {}))
    market_time = cache.get('last_quote_attempt') or cache.get('updated_at')
    payload = {
        'version': 2,
        'market_capabilities': 市场同步.capabilities(),
        'account_revision': account_revision(account),
        'account': account['account'],
        'initial_cash': account['initial_cash'],
        'facts_updated_at': account.get('facts_updated_at'),
        'market_updated_at': market_time,
        'kline_revision': account_revision(cache.get('series',{})),
        'updated_at': max(filter(None, (account.get('facts_updated_at'), market_time, nav.get('updated_at'))), default=None),
        'summary': summary,
        'pending_orders': account.get('pending_orders', []),
        'snapshots': nav.get('observations', []),
        'quote_errors': cache.get('quote_errors', []),
        'market_calendar': read_json(路径.资源路径('看板应用/资源/A股交易日历.json'))
}
    if include_kline:
        import 市场同步
        try:
            payload['market_sections'] = read_json(市场同步.market_path(path), {'sections':{}}).get('sections',{})
        except ValueError:
            payload['market_sections'] = {}
        from 指标 import chart_series
        payload['kline'] = {key:chart_series(entry,now(),key) for key,entry in cache.get('series',{}).items()}
        payload['kline_updated_at'] = cache.get('updated_at')
    return payload
