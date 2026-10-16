#!/usr/bin/env python3
"""比赛账户CLI：维护手机确认事实，行情与收益分别缓存。"""
import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sys

# 历史演练脚本按路径加载本模块，先确保同目录的兄弟模块可导入。
TOOLS_DIR = str(Path(__file__).resolve().parent)
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

import 账户核心 as core
import 行情同步 as market
import 路径

ROOT, DEFAULT = core.ROOT, core.DEFAULT
KLINE_SOURCES = market.KLINE_SOURCES
# 赛事规则费用（资料/赛事规则.md）：仅佣金，沪深万3、北交所万2.8，无印花税与过户费。
费用率 = {'SH': '0.0003', 'SZ': '0.0003', 'BJ': '0.00028', 'HK': '0.001257'}
费用标签 = {'SH': '沪深万3', 'SZ': '沪深万3', 'BJ': '北交所万2.8', 'HK': '港股通0.1257%'}

# 历史演练脚本仍可从原入口取得这些纯函数。
now, timestamp, number, money, pct = core.now, core.timestamp, core.number, core.money, core.pct
atomic_text, lock = core.atomic_text, core.lock
quote_snapshot, merge_bars = market.quote_snapshot, market.merge_bars


def validate_trade(raw):
    trade = {key: raw[key] for key in ('id', 'time', 'code', 'exchange', 'name', 'side', 'quantity', 'price')}
    if not isinstance(trade['id'], str) or not trade['id'].strip():
        raise ValueError('每笔成交必须有唯一id；部分成交分开编号')
    if trade['exchange'] not in ('SH', 'SZ', 'BJ', 'HK'):
        raise ValueError('交易所须为SH/SZ/BJ/HK')
    if not re.fullmatch(r'\d{5}' if trade['exchange'] == 'HK' else r'\d{6}', str(trade['code'])):
        raise ValueError('港股代码须为5位，沪深北须为6位')
    if trade['side'] not in ('buy', 'sell') or type(trade['quantity']) is not int or trade['quantity'] <= 0:
        raise ValueError('方向须为buy/sell，数量须为正整数')
    trade['time'] = timestamp(trade['time']) if trade['time'] else None
    trade['trade_date'] = raw.get('trade_date') or (trade['time'] or '')[:10] or None
    if trade['time'] and trade['time'] > now():
        raise ValueError('不能登记未来的成交')
    trade['price'] = str(number(trade['price'], positive=True)) if trade['price'] is not None else None
    trade['fee'] = None if raw.get('fee') is None else money(number(raw['fee']))
    trade['amount'] = money(Decimal(trade['price']) * trade['quantity']) if trade['price'] is not None else None
    # 港股通港币成交、人民币入账：成交时汇率必须随成交一起确认。
    if trade['exchange'] == 'HK':
        if raw.get('fx') in (None, ''):
            raise ValueError('港股成交需提供人民币/港币折算率')
        trade['fx'] = str(number(raw['fx'], positive=True))
    else:
        trade['fx'] = None
    if raw.get('amount') is not None and trade['amount'] is not None and money(number(raw['amount'])) != trade['amount']:
        raise ValueError('成交金额与价格×数量不一致，请核对均价精度或拆分成交')
    trade['note'] = str(raw.get('note', ''))
    trade['source'] = '用户确认的手机赛事成交'
    confirmation = raw.get('confirmation') or {}
    # fee 允许 rule：按赛事规则（沪深万3、北交所万2.8、无印花税与过户费）计算，不需要用户逐笔提供。
    allowed = {'confirmed', 'rule', 'inferred', 'unknown'}
    trade['confirmation'] = {'execution': 'confirmed', 'quantity': confirmation.get('quantity', 'unknown'),
                            'price': confirmation.get('price', 'unknown'),
                            'time': confirmation.get('time', 'unknown'),
                            'fee': confirmation.get('fee', 'unknown')}
    # 费用状态为rule时按赛事规则推定，不让用户为每笔交易手填（资料/赛事规则.md）。
    if trade['fee'] is None and trade['confirmation']['fee'] == 'rule':
        if trade['amount'] is None or not 费用率.get(trade['exchange']):
            raise ValueError('缺少成交金额或该市场无费用规则，不能标费用为rule')
        trade['fee'] = money(Decimal(trade['amount']) * Decimal(费用率[trade['exchange']]))
    if any(value not in allowed for value in trade['confirmation'].values()) or trade['confirmation']['execution'] != 'confirmed':
        raise ValueError('confirmation仅接受confirmed/inferred/unknown，且成交本身必须由用户确认')
    if trade['confirmation']['quantity'] != 'confirmed':
        raise ValueError('只有确认的实际成交数量可以入账')
    for field in ('time', 'price', 'fee'):
        permitted = ('confirmed', 'rule') if field == 'fee' else ('confirmed',)
        if trade['confirmation'][field] not in permitted:
            trade[field] = None
        elif trade[field] is None:
            raise ValueError(field + '为空不能标confirmed' + ('/rule' if field == 'fee' else ''))
    if trade['price'] is None:
        trade['amount'] = None
    return trade


def correct_confirmations(path, changes, reason):
    """仅降级错误确认状态；原值写更正链，重复调用不再写入。"""
    changed = False
    with lock(path):
        account = load(path)
        candidate = json.loads(json.dumps(account, ensure_ascii=False))
        for index, previous in enumerate(candidate['trades']):
            statuses = changes.get(previous['id'])
            if not statuses:
                continue
            raw = json.loads(json.dumps(previous))
            raw.setdefault('confirmation', {}).update(statuses)
            raw['note'] = reason
            replacement = validate_trade(raw)
            if replacement == previous:
                continue
            candidate['corrections'].append({'time': now(), 'previous': previous,
                                             'replacement': replacement, 'reason': reason})
            candidate['trades'][index] = replacement
            changed = True
        if changed:
            affected_dates = [t.get('trade_date') or (t.get('time') or '')[:10]
                              for t in candidate['trades'] if t['id'] in changes]
            cutoff = min((day for day in affected_dates if day), default=now()[:10])
            _save_fact_event(path, candidate, '字段确认状态更正')
    return changed


def calculate(data, quotes=None):
    return core.calculate(data, quotes if quotes is not None else data.get('quotes', {}))


def load(path=DEFAULT):
    return core.load_account(path)


def load_state(path=DEFAULT):
    account, cache = core.load_account(path), core.load_cache(path)
    return {'account': account, 'cache': cache, 'nav': core.load_nav(path),
            'summary': core.calculate(account, cache.get('quotes', {}))}


def cache_path(path=DEFAULT):
    return core.cache_path(path)


def kline_path(path=DEFAULT):
    return core.cache_path(path)


def load_kline(path=DEFAULT):
    cache = core.load_cache(path)
    return {'version': cache.get('version', 2), 'updated_at': cache.get('updated_at'),
            'series': cache.get('series', {})}


def _save_fact_event(path, account, event=None):
    cache = core.load_cache(path)
    summary = core.calculate(account, cache.get('quotes', {}))
    recent=dict(account.get('recent_import_ids',{}))
    recent.update({t['id']:core.account_revision(t) for t in account.get('trades',[])})
    if recent:account['recent_import_ids']=dict(list(recent.items())[-1000:])
    core.save_account(path, account)
    return summary


def init(path, initial='1000000', started=None):
    path = Path(path)
    with lock(path):
        if path.exists():
            raise ValueError('台账已存在，拒绝覆盖')
        account = {'version': 2, 'account': '全国校园模拟赛', 'currency': 'CNY',
                   'initial_cash': money(number(initial, positive=True)), 'started_at': timestamp(started or now()),
                   'baseline_source': '用户确认的初始资金与零交易基线', 'facts_updated_at': now(),
                   'trades': [], 'pending_orders': [], 'corrections': []}
        core.save_account(path, account)
        core.save_cache(path, {'version': 2, 'quotes': {}, 'series': {}, 'last_quote_attempt': None,
                               'quote_errors': [], 'updated_at': None})
        core.save_nav(path, {'version': 2, 'updated_at': None, 'observations': []})
        core.append_observation(path, '初始资金', account, core.load_cache(path))


def record(path, raw, replace=False):
    trade = validate_trade(raw)
    with lock(path):
        account = load(path)
        existing = next((item for item in account['trades'] if item['id'] == trade['id']), None)
        if not existing and trade['id'] in account.get('recent_import_ids',{}):
            raise ValueError('成交id已由手机基线覆盖，禁止重复入账')
        if existing and not replace:
            raise ValueError('成交id已存在，不能重复录入；核对后用--replace修正')
        if replace and not existing:
            raise ValueError('修正的成交id不存在')
        candidate = json.loads(json.dumps(account, ensure_ascii=False))
        if existing:
            candidate['corrections'].append({'time': now(), 'previous': existing, 'replacement': trade})
            candidate['trades'][candidate['trades'].index(existing)] = trade
        else:
            candidate['trades'].append(trade)
        core.calculate(candidate, core.load_cache(path).get('quotes', {}))
        cutoffs=[t.get('time') or t.get('trade_date') for t in (trade,existing) if t]
        cutoff=min((v for v in cutoffs if v),default=now()[:10])
        if not existing and any(raw.get(k) is not None and trade.get(k) is None for k in ('price','time','fee')):
            reference={k:raw.get(k) for k in ('id','time','trade_date','code','exchange','name','side','quantity','price','fee','confirmation','note')}
            candidate['corrections'].append({'time':now(),'previous':reference,'replacement':trade,
                                             'reason':'未明确确认字段转为待核，旧输入仅作参考'})
        _save_fact_event(path, candidate, '修正成交' if replace else '登记成交')


def revoke(path, trade_id, reason=''):
    """撤销误入账成交：移出trades，在corrections留previous与replacement=null。"""
    with lock(path):
        account = load(path)
        existing = next((item for item in account['trades'] if item['id'] == trade_id), None)
        if not existing:
            raise ValueError('待撤销的成交id不存在：' + trade_id)
        candidate = json.loads(json.dumps(account, ensure_ascii=False))
        candidate['trades'] = [item for item in candidate['trades'] if item['id'] != trade_id]
        candidate['corrections'].append({'time': now(), 'previous': existing, 'replacement': None,
                                         'reason': reason or '误入账撤销'})
        core.calculate(candidate, core.load_cache(path).get('quotes', {}))
        _save_fact_event(path, candidate, '撤销成交')
    return trade_id


def validate_pending(raw):
    order = {'id': str(raw['id']).strip(), 'time': timestamp(raw['time']), 'code': str(raw['code']),
             'exchange': str(raw['exchange']), 'name': str(raw['name']), 'side': str(raw.get('side', 'buy')),
             'price': str(number(raw['price'], positive=True)), 'quantity': int(raw['quantity']),
             'status': str(raw.get('status', '待成交')), 'note': str(raw.get('note', ''))}
    if not order['id']:
        raise ValueError('每笔委托必须有唯一id')
    if order['exchange'] not in ('SH', 'SZ', 'BJ', 'HK'):
        raise ValueError('交易所须为SH/SZ/BJ/HK')
    if not re.fullmatch(r'\d{5}' if order['exchange'] == 'HK' else r'\d{6}', order['code']):
        raise ValueError('港股代码须为5位，沪深北须为6位')
    if order['side'] not in ('buy', 'sell') or type(raw.get('quantity')) is not int or order['quantity'] <= 0:
        raise ValueError('方向须为buy/sell，数量须为正整数')
    filled,remaining=raw.get('filled_quantity'),raw.get('remaining_quantity')
    if filled is not None or remaining is not None:
        if any(type(v) is not int or v<0 for v in (filled,remaining) if v is not None):
            raise ValueError('已成／剩余数量须为非负整数')
        if filled is None:filled=order['quantity']-remaining
        if remaining is None:remaining=order['quantity']-filled
        if filled<0 or remaining<0 or filled+remaining!=order['quantity']:
            raise ValueError('已成与剩余数量必须合计原委托量')
        order.update(filled_quantity=filled,remaining_quantity=remaining)
    order['amount'] = money(Decimal(order['price']) * order['quantity'])
    order['currency'] = 'HKD' if order['exchange'] == 'HK' else 'CNY'
    if order['exchange'] == 'HK':
        if raw.get('fx') in (None, ''):
            raise ValueError('港股委托需提供人民币/港币折算率')
        order['fx'] = str(number(raw['fx'], positive=True))
    else:
        order['fx'] = None
    order['source'] = '用户确认的手机赛事委托'
    return order


def pending(path, items):
    normalized, seen = [validate_pending(item) for item in items], set()
    for order in normalized:
        if order['id'] in seen:
            raise ValueError('委托id重复：' + order['id'])
        seen.add(order['id'])
    with lock(path):
        account = load(path)
        account['pending_orders'] = normalized
        _save_fact_event(path, account)
    return len(normalized)


def validate_reconciliation(account, raw, quotes=None):
    """纯校验与报告构建，网页预览和CLI共用。"""
    # 港股折算率：手机填写的优先，其次缓存实时汇率；都没有时港股持仓拒绝入账。
    rate = number(raw['fx'], positive=True) if raw.get('fx') not in (None, '') else core.hk_rate(account, quotes)
    report_id = str(raw['id']).strip()
    if not report_id or any(r['id'] == report_id for r in account.get('reconciliations', [])):
        raise ValueError('对账id为空或已存在，不重复覆盖')
    if any(o.get('status') != '已撤' for o in account.get('pending_orders', [])):
        raise ValueError('尚有委托冻结，不能将可用资金直接作为现金基线')
    header = raw['summary']
    summary = {key: money(number(header[key])) for key in ('total_assets','market_value','available_cash')}
    for key in ('daily_profit', 'unrealized_profit'):
        if header.get(key) in (None, ''):
            summary[key] = None
            continue
        value = Decimal(str(header[key]))
        if not value.is_finite(): raise ValueError('盈亏必须为有限数')
        summary[key] = money(value)
    if Decimal(summary['total_assets']) != Decimal(summary['market_value']) + Decimal(summary['available_cash']):
        raise ValueError('总资产必须等于总市值加现金；存在冻结请提供独立现金余额')
    expected = {p['key']:p['quantity'] for p in core.calculate(account, quotes)['positions']}
    positions, seen = [], set()
    for row in raw['positions']:
        p = {k: row[k] for k in ('code','exchange','name','quantity')}
        key = p['exchange'] + ':' + p['code']
        if p['exchange'] not in ('SH','SZ','BJ','HK') or not re.fullmatch(
                r'\d{5}' if p['exchange']=='HK' else r'\d{6}', p['code']):
            raise ValueError('对账代码或市场无效')
        if key in seen or row.get('key', key) != key or type(p['quantity']) is not int or p['quantity'] <= 0:
            raise ValueError('对账持仓重复、数量或代码无效')
        seen.add(key)
        p.update(key=key, average_cost=str(number(row['average_cost'],positive=True)),
                 price=str(number(row['price'],positive=True)))
        unit = rate if p['exchange']=='HK' else Decimal(1)
        if unit is None:
            raise ValueError('港股持仓缺少人民币折算率，先刷新行情再对账')
        p.update(currency='HKD' if p['exchange']=='HK' else 'CNY',
                 fx=str(unit) if p['exchange']=='HK' else None)
        # 可卖数量仅供卖出审查；手机未给出时保持未知，不拿持仓总量顶替。
        available = row.get('available_quantity')
        if available is None:
            p['available_quantity'] = None
        elif type(available) is int and 0 <= available <= p['quantity']:
            p['available_quantity'] = available
        else:
            raise ValueError('可卖数量必须是0到持仓数量之间的整数')
        positions.append(p)
    # 期初基线：全新台账（无成交、无历史对账）允许直接用手机持仓开账，用于队友带着已有的仓入场。
    opening = not account.get('trades') and not account.get('reconciliations')
    if {p['key']:p['quantity'] for p in positions} != expected and not opening:
        raise ValueError('手机持仓数量与已确认成交不同，先更正成交，不自动造交易')
    stamp = now()
    reported_at = timestamp(raw['reported_at']) if raw.get('reported_at') else None
    if reported_at and reported_at > stamp: raise ValueError('不能登记未来账户时点')
    row_value, display_cost = Decimal(0), Decimal(0)
    for p in positions:
        unit = Decimal(p['fx']) if p.get('fx') else Decimal(1)
        row_value += Decimal(p['price']) * p['quantity'] * unit
        display_cost += Decimal(p['average_cost']) * p['quantity'] * unit
    report = {'id':report_id,'recorded_at':stamp,'reported_at':reported_at,
        'source':'用户口述手机全国校园模拟赛账户','source_ref':str(raw.get('source_ref','本次用户账户回报')),
        'summary':summary,'positions':positions,
        'covered_trade_count':len(account['trades']),'trade_basis':core.trade_digest(account['trades']),
        'checks':{'row_market_value':money(row_value),
                  'market_value_difference':money(row_value-Decimal(summary['market_value'])),
                  'display_cost_difference':money(Decimal(summary['market_value'])-Decimal(summary['unrealized_profit'])-display_cost)
                      if summary['unrealized_profit'] is not None else None},
        'note':'显示均价不拆成裸成交价和费用；逐项价格与总额差异保留，不分摊或抹平。'}
    if opening:
        # 期初基线：成交明细不追溯，收益率以初始资金为基准，已实现盈亏视为未知。
        report.update(opening=True,
            source='用户口述手机全国校园模拟赛账户（期初基线）',
            source_ref=str(raw.get('source_ref','队友开账：当前持仓与可用资金')))
        report['note'] = '期初基线：开账前成交与已实现盈亏未追溯；此后成交按确认逐笔入账。'
    account.setdefault('reconciliations', []).append(report)
    return report


def reconcile(path, raw):
    with lock(path):
        account = load(path)
        report = validate_reconciliation(account, raw)
        _save_fact_event(path, account, '手机账户对账')
    return report

def compact(path=DEFAULT):
    """将账户压缩为当前手机基线，不保留已过期成交、修正与旧对账记录。"""
    path = Path(path)
    with lock(path):
        account = load(path)
        reports = account.get('reconciliations', [])
        if not reports:
            raise ValueError('无手机对账基线，不能压缩为当前状态')
        report = json.loads(json.dumps(reports[-1], ensure_ascii=False))
        if (report['covered_trade_count'] != len(account['trades']) or
                report['trade_basis'] != core.trade_digest(account['trades'])):
            raise ValueError('尚有未被当前手机基线覆盖的成交，先完成对账再压缩')
        report['id'] = '当前账户状态'
        report['source'] = '用户确认的当前手机账户状态'
        report['source_ref'] = '当前状态快照'
        report['covered_trade_count'] = 0
        report['trade_basis'] = core.trade_digest([])
        report['note'] = '当前账户快照；历史成交与更正已清除。'
        compacted = {key: account[key] for key in ('version', 'account', 'currency', 'initial_cash',
                    'started_at', 'baseline_source')}
        compacted.update({'facts_updated_at': report['recorded_at'], 'trades': [],
                          'pending_orders': account.get('pending_orders', []), 'corrections': [],
                          'reconciliations': [report]})
        if account.get('recent_import_ids'):
            compacted['recent_import_ids'] = account['recent_import_ids']
        core.save_account(path, compacted)
        summary = core.calculate(compacted, core.load_cache(path).get('quotes', {}))
    return summary


def refresh(path=DEFAULT):
    return market.refresh(path)


def sync(path=DEFAULT, granularities=('m5', 'day'), use_quote=True):
    return market.sync(path, granularities, use_quote)


def render(path=DEFAULT):
    template = 路径.资源路径('看板应用/源码/账户看板模板.html').read_text(encoding='utf-8')
    import 投研缓存,市场同步
    data=core.view_model(path, include_kline=True)
    data['research']=投研缓存.load(path)
    data['market_sections'].update({key:市场同步.read_section(path,key) for key in ('summary','fund_flows','huatai')})
    payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c')
    library = 路径.资源路径('看板应用/源码/图表依赖/echarts.min.js').read_text(encoding='utf-8').replace('</script', '<\\/script')
    html = template.replace('__ACCOUNT_DATA__', payload).replace('__CHART_TAG__', '') \
        .replace('__CHART_LIBRARY__', library).replace('__LOCAL_TOKEN__', '').replace('__LIVE_REVISION__', '')
    script = '\n'.join(路径.资源路径('看板应用/源码/'+name).read_text(encoding='utf-8')
                       for name in ('页面导航.js','市场看板.js','投研看板.js','产品分析.js','账户录入.js')).replace('</script','<\\/script')
    html = html.replace('__EXTRA_SCRIPTS__','<script>'+script+'</script>')
    core.atomic_text(Path(path).with_name('比赛账户看板.html'), html)


def migrate(path=DEFAULT):
    with lock(path):
        return core.migrate(path)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, default=DEFAULT, help='其他台账路径，仅测试或独立账户用')
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('init', 'show', 'render', 'refresh', 'migrate', 'compact'):
        sub.add_parser(command)
    sync_cmd = sub.add_parser('sync')
    sync_cmd.add_argument('--granularity', action='append', choices=list(KLINE_SOURCES))
    sync_cmd.add_argument('--no-quote', action='store_true')
    pending_cmd = sub.add_parser('pending')
    pending_cmd.add_argument('--input', type=Path)
    pending_cmd.add_argument('--clear', action='store_true')
    record_cmd = sub.add_parser('record')
    record_cmd.add_argument('--input', type=Path, required=True)
    record_cmd.add_argument('--replace', action='store_true')
    revoke_cmd = sub.add_parser('revoke')
    revoke_cmd.add_argument('--id', required=True)
    revoke_cmd.add_argument('--reason', default='')
    reconcile_cmd = sub.add_parser('reconcile')
    reconcile_cmd.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'init':
            init(args.file)
        elif args.command == 'migrate':
            print(json.dumps({'迁移': '完成' if migrate(args.file) else '无需迁移'}, ensure_ascii=False))
        elif args.command == 'compact':
            print(json.dumps({'压缩': '完成', 'summary': compact(args.file)}, ensure_ascii=False))
        elif args.command == 'record':
            record(args.file, json.loads(args.input.read_text(encoding='utf-8-sig')), args.replace)
        elif args.command == 'revoke':
            print(json.dumps({'已撤销': revoke(args.file, args.id, args.reason)}, ensure_ascii=False))
        elif args.command == 'reconcile':
            reconcile(args.file, json.loads(args.input.read_text(encoding='utf-8-sig')))
        elif args.command == 'pending':
            if args.clear:
                items = []
            elif args.input:
                items = json.loads(args.input.read_text(encoding='utf-8-sig'))
            else:
                raise ValueError('pending需要--input或--clear')
            print(json.dumps({'已写入委托条数': pending(args.file, items)}, ensure_ascii=False))
        elif args.command == 'refresh':
            report = refresh(args.file)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 2 if report['报价失败'] else 0
        elif args.command == 'sync':
            report = sync(args.file, tuple(args.granularity or ('m5', 'day')), not args.no_quote)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 2 if report['报价失败'] or report['K线失败'] else 0
        elif args.command == 'render':
            render(args.file)
        state = load_state(args.file)
        print(json.dumps({'account': state['account']['account'],
                          'facts_updated_at': state['account'].get('facts_updated_at'),
                          'market_updated_at': state['cache'].get('last_quote_attempt'),
                          'summary': state['summary']}, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, InvalidOperation) as exc:
        print('台账操作失败：' + (str(exc) if isinstance(exc, (ValueError, InvalidOperation)) else type(exc).__name__))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
