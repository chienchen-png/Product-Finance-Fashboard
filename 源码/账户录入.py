"""事实录入的预览与原子提交。只处理用户确认信息，不取行情，不渲染网页。"""
import argparse
import copy
import csv
from datetime import date
import io
import json
from pathlib import Path
import 账户核心 as core
import 账户台账 as ledger
from 数据契约 import exchange_of, validate_symbol


class RevisionConflict(ValueError):pass


def _rows(payload):
    if payload.get('csv') is not None:
        rows=list(csv.DictReader(io.StringIO(str(payload['csv']).lstrip('\ufeff'))))
        for row in rows:
            for field in ('quantity','filled_quantity','remaining_quantity'):
                if row.get(field) not in (None,''):row[field]=int(row[field])
            for field in ('price','fee','time','trade_date'):
                if row.get(field)=='':row[field]=None
    else:rows=payload.get('rows',[])
    if not isinstance(rows,list) or len(rows)>1000:raise ValueError('导入限1000行')
    return rows


def 费用规则():
    """录入表单预估费用：单一事实源为赛事规则费用率，网页只读展示。"""
    return {market: {'rate': rate, 'label': ledger.费用标签.get(market, market)}
            for market, rate in ledger.费用率.items()}


def preview_import(account: dict, payload: dict, quotes: dict|None = None) -> dict:
    candidate=copy.deepcopy(account)
    result=dict(errors=[],normalized=candidate,changes=[],revision=core.account_revision(account),kind=payload.get('kind'))
    try:
        if len(json.dumps(payload,ensure_ascii=False).encode())>1024*1024:raise ValueError('导入正文超过1MiB')
        kind=payload.get('kind');rows=_rows(payload)
        if kind=='trades':
            recent=dict(candidate.get('recent_import_ids',{}))
            existing={t['id']:t for t in candidate.get('trades',[])}
            for i,raw in enumerate(rows,1):
                try:
                    row=dict(raw)
                    row.setdefault('time',None);row.setdefault('price',None);row.setdefault('name',str(row.get('code','')))
                    # 交易所由代码前缀推导并校验：用户只填代码。
                    row['exchange']=exchange_of(row.get('code'),row.get('exchange'))
                    if row['price'] is not None:row['price']=format(core.number(row['price'],positive=True).normalize(),'f')
                    # 缺成交编号时按内容生成稳定编号：同一笔重复导入仍被识别为重复，不产生第二笔。
                    automatic_id=not str(row.get('id') or '').strip()
                    if automatic_id:row['id']='自动-待生成'
                    # 手动确认后仅将实际填入字段标confirmed，空白保持unknown。
                    row.setdefault('confirmation',dict(quantity='confirmed',**{
                        key:'confirmed' if row.get(key) not in (None,'') else 'unknown' for key in ('price','fee','time')}))
                    # 表单留空费用＝按赛事规则自动算，不要求用户逐笔查手续费；价格未确认时仍留空。
                    if (row['confirmation']['fee']=='unknown' and row['confirmation']['price']=='confirmed'
                            and ledger.费用率.get(str(row.get('exchange','')).upper())):
                        row['confirmation']['fee']='rule'
                    if row.get('trade_date'):
                        day=date.fromisoformat(row['trade_date'])
                        if day>date.fromisoformat(core.now()[:10]) or day<date.fromisoformat(account['started_at'][:10]):
                            raise ValueError('成交日期超出账户区间')
                    trade=ledger.validate_trade(row)
                    if automatic_id:
                        trade['id']='自动-'+core.account_revision({key:trade.get(key) for key in
                            ('code','exchange','side','quantity','price','time','fx')})[:16]
                    digest=core.account_revision(trade)
                    if trade['id'] in existing:
                        if existing[trade['id']]!=trade:raise ValueError('同一成交id内容不同，请用更正命令处理')
                        continue
                    if trade['id'] in recent:
                        if recent[trade['id']]!=digest:raise ValueError('已处理成交id内容冲突')
                        continue
                    candidate.setdefault('trades',[]).append(trade);existing[trade['id']]=trade
                    recent[trade['id']]=digest
                    result['changes'].append({'id':trade['id'],'action':'新增成交','quantity':trade['quantity'],
                        'price':trade['price'],'fee':trade['fee'],'time':trade['time']})
                except (KeyError,ValueError,TypeError,ArithmeticError) as exc:result['errors'].append(f'第{i}行：{exc}')
            if result['changes']:candidate['recent_import_ids']=dict(list(recent.items())[-1000:])
            core.calculate(candidate)
        elif kind=='pending':
            append=bool(payload.get('append'))
            previous=[o for o in account.get('pending_orders',[]) if o.get('status')!='已撤'] if append else []
            normalized=[]
            for i,raw in enumerate(rows,1):
                try:
                    order=dict(raw)
                    order['exchange']=exchange_of(order.get('code'),order.get('exchange'))
                    order['name']=str(order.get('name') or order.get('code') or '')
                    raw_time=order.get('time')
                    if not raw_time:order['time']=core.now()
                    automatic=not str(order.get('id') or '').strip()
                    if automatic:order['id']='自动-待生成'
                    item=ledger.validate_pending(order)
                    if automatic:
                        # 未提供提交时间的委托按内容去重，重复提交不产生第二笔。
                        basis={key:item.get(key) for key in ('code','exchange','side','quantity','price')}
                        if raw_time:basis['time']=item['time']
                        item['id']='自动-'+core.account_revision(basis)[:16]
                    normalized.append(item)
                except (KeyError,ValueError,TypeError,ArithmeticError) as exc:result['errors'].append(f'第{i}行：{exc}')
            normalized=previous+normalized
            if len({r['id'] for r in normalized})!=len(normalized):raise ValueError('委托id重复（同一笔不要重复提交）')
            candidate['pending_orders']=normalized
            result['changes']=[{'action':'追加委托' if append else '替换当前委托',
                                'count':len(normalized)-len(previous) if append else len(normalized)}]
        elif kind=='snapshot':
            raw=payload.get('snapshot')
            if not isinstance(raw,dict):raise ValueError('需要summary及positions账户快照')
            report=ledger.validate_reconciliation(candidate,raw,quotes)
            candidate['reconciliations']=[report]
            result['changes']=[{'action':'更新手机快照','summary':report['summary'],'checks':report['checks']}]
        elif kind=='watchlist':
            products=[]
            for raw in rows:
                symbol=validate_symbol(raw['symbol'])
                products.append(dict(symbol=symbol,name=str(raw.get('name',symbol))[:100],
                    product_type=str(raw.get('product_type','watch'))[:20]))
            if len(products)>40 or len({r['symbol'] for r in products})!=len(products):raise ValueError('本地自选限40项且不得重复')
            from 市场同步 import public
            own={p['key'] for p in core.calculate(account)['positions']}
            if len(own|{s for s,_,_ in public.BENCHMARKS}|{r['symbol'] for r in products})>50:raise ValueError('持仓、自选、基准合计超过50项')
            result['normalized']={'schema_version':1,'products':products}
            result['changes']=[{'action':'替换本地自选','count':len(products)}]
        else:raise ValueError('仅支持trades/pending/snapshot/watchlist')
    except (KeyError,ValueError,TypeError,ArithmeticError) as exc:result['errors'].append(str(exc))
    return result


def commit_import(path: Path, payload: dict, expected_revision: str) -> dict:
    with core.lock(path):
        account=core.load_account(path)
        if core.account_revision(account)!=expected_revision:raise RevisionConflict('账户已被更新，请重新预览')
        preview=preview_import(account,payload,core.load_cache(path).get('quotes', {}))
        if preview['errors']:raise ValueError('；'.join(preview['errors']))
        normalized=preview['normalized']
        if payload['kind']=='watchlist':
            from 市场同步 import watchlist_path
            target=watchlist_path(path)
            with core.lock(target):
                old=core.read_json(target,{'schema_version':1,'products':[]})
                if payload.get('expected_watchlist_revision')!=core.account_revision(old):
                    raise RevisionConflict('本地自选已变化，请重新预览')
                if old!=normalized:core.write_json(target,normalized)
            return dict(revision=expected_revision,changes=preview['changes'])
        if normalized!=account:core.save_account(path,normalized)
        return dict(revision=core.account_revision(normalized),changes=preview['changes'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('preview','commit'))
    parser.add_argument('--input',type=Path,required=True);parser.add_argument('--file',type=Path,default=core.DEFAULT)
    parser.add_argument('--revision')
    args=parser.parse_args()
    try:
        payload=json.loads(args.input.read_text(encoding='utf-8-sig'))
        if payload.get('kind')=='watchlist' and args.command=='preview':
            from 市场同步 import watchlist_path
            payload['expected_watchlist_revision']=core.account_revision(core.read_json(watchlist_path(args.file),{'schema_version':1,'products':[]}))
        if args.command=='commit':
            if not args.revision:raise ValueError('commit需要预览的--revision')
            result=commit_import(args.file,payload,args.revision)
        else:
            result=preview_import(core.load_account(args.file),payload,core.load_cache(args.file).get('quotes', {}))
            if 'expected_watchlist_revision' in payload:result['expected_watchlist_revision']=payload['expected_watchlist_revision']
        print(json.dumps(result,ensure_ascii=False,indent=2));return int(bool(result.get('errors')))
    except (ValueError,OSError,TypeError) as exc:
        print(json.dumps({'errors':[str(exc)]},ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
