import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码'))
"""仅使用临时目录验证账务、分层存储与离线页面，不访问网络或正式账户。"""
import json
from pathlib import Path
import tempfile
import unittest

import 账户核心 as core
import 账户台账 as ledger


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / '账户.json'
        ledger.init(self.path, started='2026-10-10T00:00:00+08:00')

    def tearDown(self):
        self.folder.cleanup()

    def trade(self, **changes):
        result = dict(id='001', time=ledger.now(), code='601688', exchange='SH', name='华泰证券',
                      side='buy', quantity=100, price='10', fee='5',
                      confirmation={'quantity':'confirmed','price':'confirmed','time':'confirmed','fee':'confirmed'})
        result.update(changes)
        if 'confirmation' not in changes:
            if result['fee'] is None:result['confirmation']['fee']='unknown'
        return result

    def set_quote(self, key, price, **fields):
        cache = core.load_cache(self.path)
        quote = dict(price=price, requested_at=ledger.now(), market_time=ledger.now(), source='测试报价')
        quote.update(fields)
        cache.setdefault('quotes', {})[key] = quote
        core.save_cache(self.path, cache)

    def test_facts_keep_only_confirmed_records(self):
        ledger.record(self.path, self.trade())
        facts = ledger.load(self.path)
        for key in ('quotes', 'summary', 'snapshots', 'quote_history', 'symbol_notes'):
            self.assertNotIn(key, facts)
        self.assertEqual(facts['version'], 2)
        self.assertEqual([item['id'] for item in facts['trades']], ['001'])
        self.assertEqual(ledger.load_state(self.path)['cache']['quotes'], {})

    def test_cash_cost_realized_profit_and_quote(self):
        ledger.record(self.path, self.trade())
        self.assertEqual(ledger.load_state(self.path)['summary']['cash'], '998995.00')
        self.set_quote('SH:601688', '12')
        self.assertEqual(ledger.load_state(self.path)['summary']['profit'], '195.00')
        ledger.record(self.path, self.trade(id='002', side='sell', quantity=50, price='12'))
        summary = ledger.load_state(self.path)['summary']
        self.assertEqual(summary['realized_profit'], '92.50')
        self.assertEqual(summary['profit'], '190.00')
        self.assertEqual(summary['positions'][0]['quantity'], 50)
        ledger.record(self.path, self.trade(id='003', side='sell', quantity=50, price='12'))
        summary = ledger.load_state(self.path)['summary']
        self.assertEqual(summary['positions'], [])
        self.assertEqual(summary['cash'], '1000185.00')
        self.assertEqual(summary['profit'], summary['realized_profit'])

    def test_revoke_removes_trade_and_keeps_history(self):
        ledger.record(self.path, self.trade())
        self.assertEqual(ledger.load_state(self.path)['summary']['cash'], '998995.00')
        ledger.revoke(self.path, '001', '废单误入账')
        facts = ledger.load(self.path)
        self.assertEqual(facts['trades'], [])
        self.assertEqual(len(facts['corrections']), 1)
        self.assertIsNone(facts['corrections'][0]['replacement'])
        self.assertEqual(facts['corrections'][0]['reason'], '废单误入账')
        self.assertEqual(facts['corrections'][0]['previous']['id'], '001')
        self.assertEqual(ledger.load_state(self.path)['summary']['cash'], '1000000.00')
        with self.assertRaises(ValueError):
            ledger.revoke(self.path, '不存在')

    def test_rejected_changes_do_not_mutate(self):
        ledger.record(self.path, self.trade())
        before = self.path.read_bytes()
        for trade in (self.trade(), self.trade(id='002', side='sell', quantity=101),
                      self.trade(id='003', quantity=200000), self.trade(id='004', amount='999')):
            with self.assertRaises(ValueError):
                ledger.record(self.path, trade)
            self.assertEqual(self.path.read_bytes(), before)

    def test_correction_fee_flag_and_snapshot_history(self):
        ledger.record(self.path, self.trade(fee=None))
        core.observe_account(self.path)
        before = ledger.load_state(self.path)
        self.assertEqual(before['summary']['unknown_fee_ids'], ['001'])
        ledger.record(self.path, self.trade(fee='5'), replace=True)
        core.observe_account(self.path)
        after = ledger.load_state(self.path)
        self.assertEqual(after['summary']['unknown_fee_ids'], [])
        self.assertEqual(len(after['account']['corrections']), 1)
        for new,old in zip(after['nav']['observations'][:2],before['nav']['observations']):
            for field in ('time','event','total_assets','return_pct'):
                self.assertEqual(new[field],old[field])
        self.assertFalse(after['nav']['observations'][1]['valid'])
        self.assertEqual(after['summary']['cash'], '998995.00')

    def test_offline_html_payload_and_initial_state(self):
        summary = ledger.load_state(self.path)['summary']
        self.assertEqual(summary['total_assets'], '1000000.00')
        self.assertEqual(summary['return_pct'], '0.0000')
        ledger.record(self.path, self.trade(name='</script><script>alert(1)</script>'))
        ledger.render(self.path)
        html = self.path.with_name('比赛账户看板.html').read_text(encoding='utf-8')
        self.assertNotIn('</script><script>alert(1)', html)
        self.assertNotIn('__ACCOUNT_DATA__', html)
        self.assertNotIn('__CHART_TAG__', html)
        self.assertNotIn('<script src=""></script>', html)
        payload = html.split('<script id="account-data" type="application/json">')[1].split('</script>')[0]
        self.assertEqual(json.loads(payload)['summary'], ledger.load_state(self.path)['summary'])

    def test_empty_account_refresh_does_not_pile_up_snapshots(self):
        self.assertEqual(ledger.refresh(self.path)['报价失败'], [])
        after_first = ledger.load_state(self.path)
        self.assertEqual(after_first['nav']['observations'][-1]['event'], '空仓估值')
        ledger.refresh(self.path)
        self.assertEqual(len(ledger.load_state(self.path)['nav']['observations']),
                         len(after_first['nav']['observations']))

    def test_quote_snapshot_keeps_day_change_and_limits(self):
        ledger.record(self.path, self.trade())
        payload = {'stockName': '华泰证券', 'currentPrice': 12, 'prevClose': 11.5, 'limitUp': 12.65,
                   'limitDown': 10.35, 'bidPrice1': 11.99, 'askPrice1': 12, 'change': 4.3478,
                   'isSuspended': False}
        snapshot = ledger.quote_snapshot(payload)
        self.assertEqual(snapshot['price'], '12')
        self.assertEqual(snapshot['change_pct'], '4.3478')
        self.assertEqual(snapshot['limit_up'], '12.65')
        self.set_quote('SH:601688', snapshot.pop('price'), **snapshot)
        position = ledger.load_state(self.path)['summary']['positions'][0]
        self.assertEqual(position['key'], 'SH:601688')
        self.assertTrue(position['quote_fresh'])
        self.assertEqual(position['change_pct'], '4.3478')
        self.assertEqual(position['limit_down'], '10.35')

    def test_tolerates_legacy_quote_without_new_fields(self):
        ledger.record(self.path, self.trade())
        self.set_quote('SH:601688', '12', source='旧版报价')
        position = ledger.load_state(self.path)['summary']['positions'][0]
        self.assertIsNone(position['change_pct'])
        self.assertFalse(position['suspended'])

    def test_corrupt_cache_is_read_only_without_touching_facts(self):
        ledger.record(self.path, self.trade())
        ledger.atomic_text(ledger.kline_path(self.path), '{ bad json')
        self.assertEqual(core.load_cache(self.path)['series'], {})
        self.assertEqual(core.load_cache(self.path)['quotes'], {})
        self.assertEqual(core.cache_path(self.path).read_text(encoding='utf-8'), '{ bad json')
        self.assertFalse(core.cache_path(self.path).with_suffix('.损坏').exists())
        self.assertEqual(ledger.load_state(self.path)['summary']['cash'], '998995.00')
        self.assertEqual(ledger.load(self.path)['trades'][0]['id'], '001')

    def test_migrate_v1_splits_files_and_archives_source(self):
        folder = self.path.parent
        v1 = {'version': 1, 'account': '测试', 'currency': 'CNY', 'initial_cash': '100000.00',
              'started_at': '2026-01-01T00:00:00+08:00', 'baseline_source': 'x', 'trades': [],
              'quotes': {'SH:600000': {'price': '1', 'requested_at': '2026-01-02T10:00:00+08:00', 'source': 's'}},
              'snapshots': [{'time': '2026-01-01T00:00:00+08:00', 'event': '初始资金',
                             'total_assets': '100000.00', 'return_pct': '0.0000', 'provisional': False}],
              'corrections': [], 'pending_orders': [],
              'symbol_notes': {'SH:600000': [{'time': '2026-01-02T10:00:00+08:00', 'kind': '复盘', 'text': 'x'}]},
              'updated_at': '2026-01-02T10:00:00+08:00'}
        legacy = folder / '旧账户.json'
        legacy.write_text(json.dumps(v1, ensure_ascii=False), encoding='utf-8')
        (folder / '行情K线.json').write_text(json.dumps(
            {'version': 1, 'series': {'SH:600000': {'day': {'bars': [['2026-01-02', '1', '2', '3', '0.5', '10']]}}}},
            ensure_ascii=False), encoding='utf-8')
        self.assertTrue(ledger.migrate(legacy))
        self.assertFalse(ledger.migrate(legacy))
        facts = json.loads(legacy.read_text(encoding='utf-8'))
        self.assertEqual(facts['version'], 2)
        for key in ('quotes', 'snapshots', 'symbol_notes'):
            self.assertNotIn(key, facts)
        cache = json.loads((folder / '行情缓存.json').read_text(encoding='utf-8'))
        self.assertEqual(cache['quotes']['SH:600000']['price'], '1')
        self.assertEqual(len(cache['series']['SH:600000']['day']['bars']), 1)
        nav = json.loads((folder / '收益曲线.json').read_text(encoding='utf-8'))
        self.assertEqual(nav['observations'][0]['event'], '初始资金')
        self.assertFalse((folder / '行情K线.json').exists())
        self.assertEqual(len(list((folder / '历史归档').glob('*.json'))), 2)

    def test_pending_orders_do_not_touch_positions_or_summary(self):
        ledger.record(self.path, self.trade())
        before = ledger.load_state(self.path)['summary']
        snapshots_before = len(ledger.load_state(self.path)['nav']['observations'])
        ledger.pending(self.path, [
            {'id': 'P1', 'time': '2026-10-14T18:10:00+08:00', 'code': '512890', 'exchange': 'SH',
             'name': '红利低波ETF', 'price': '1.233', 'quantity': 90000, 'note': '卖一价+0.001'},
            {'id': 'P2', 'time': '2026-10-14T18:10:00+08:00', 'code': '513100', 'exchange': 'SH',
             'name': '纳指ETF', 'price': '2.4', 'quantity': 40000},
        ])
        data = ledger.load(self.path)
        self.assertEqual(ledger.load_state(self.path)['summary'], before)
        self.assertEqual(before['cash'], '998995.00')
        self.assertEqual(len(data['pending_orders']), 2)
        self.assertEqual(data['pending_orders'][0]['amount'], '110970.00')
        self.assertEqual(data['pending_orders'][0]['status'], '待成交')
        self.assertEqual(data['pending_orders'][1]['side'], 'buy')
        self.assertEqual(len(ledger.load_state(self.path)['nav']['observations']), snapshots_before)
        for bad in ({'id': 'P3', 'time': '2026-10-14T18:10:00+08:00', 'code': '512890',
                     'exchange': 'XX', 'name': 'x', 'price': '1', 'quantity': 100},
                    {'id': 'P4', 'time': '2026-10-14T18:10:00+08:00', 'code': '512890',
                     'exchange': 'SH', 'name': 'x', 'price': '1', 'quantity': '100'},
                    {'id': 'P5', 'time': '2026-10-14T18:10:00+08:00', 'code': '512890',
                     'exchange': 'SH', 'name': 'x', 'price': '0', 'quantity': 100}):
            with self.assertRaises(ValueError):
                ledger.pending(self.path, [bad])
        with self.assertRaises(ValueError):
            ledger.pending(self.path, [{'id': 'dup', 'time': '2026-10-14T18:10:00+08:00', 'code': '512890',
                                        'exchange': 'SH', 'name': 'x', 'price': '1', 'quantity': 100},
                                       {'id': 'dup', 'time': '2026-10-14T18:10:00+08:00', 'code': '513100',
                                        'exchange': 'SH', 'name': 'y', 'price': '1', 'quantity': 100}])
        self.assertEqual(len(ledger.load(self.path)['pending_orders']), 2)

    def test_kline_merge_is_incremental_and_time_sorted(self):
        stored = [['2026-10-13', '1', '2', '3', '0.5', '10'], ['2026-10-14', '2', '2.5', '3', '1', '20']]
        fresh = [['2026-10-14', '2', '2.8', '3', '1', '25'], ['2026-10-15', '2.8', '3', '3.2', '2.7', '30']]
        bars, added = ledger.merge_bars(stored, fresh, 10)
        self.assertEqual(added, 1)
        self.assertEqual([bar[0] for bar in bars], ['2026-10-13', '2026-10-14', '2026-10-15'])
        self.assertEqual(bars[1][2], '2.8')
        capped, _ = ledger.merge_bars(bars, [], 2)
        self.assertEqual([bar[0] for bar in capped], ['2026-10-14', '2026-10-15'])
        self.assertEqual(ledger.load_kline(self.path)['series'], {})

    def test_unknown_price_and_fee_do_not_create_exact_cash(self):
        ledger.record(self.path, self.trade(price=None, fee=None,
                      confirmation={'quantity':'confirmed','price': 'unknown', 'fee': 'unknown'}))
        self.set_quote('SH:601688', '12')
        summary = ledger.load_state(self.path)['summary']
        self.assertIsNone(summary['cash'])
        self.assertIsNone(summary['total_assets'])
        self.assertIsNone(summary['positions'][0]['average_cost'])
        self.assertEqual(summary['market_value'], '1200.00')
        self.assertEqual(summary['positions'][0]['quantity'], 100)
        self.assertTrue(summary['provisional'])

    def test_unknown_fee_is_not_zero_fee(self):
        ledger.record(self.path, self.trade(fee=None))
        self.assertIsNone(ledger.load_state(self.path)['summary']['profit'])
        ledger.record(self.path, self.trade(fee='0'), replace=True)
        self.assertEqual(ledger.load_state(self.path)['summary']['cash'], '999000.00')

    def test_inferred_fields_removed_but_evidence_retained(self):
        ledger.record(self.path, self.trade())
        self.assertTrue(ledger.correct_confirmations(self.path,
            {'001': {'price': 'inferred', 'time': 'inferred', 'fee': 'inferred'}}, '审计'))
        facts = ledger.load(self.path)
        self.assertIsNone(facts['trades'][0]['price'])
        self.assertIsNone(facts['trades'][0]['time'])
        self.assertEqual(facts['trades'][0]['confirmation']['quantity'], 'confirmed')
        self.assertEqual(facts['corrections'][-1]['previous']['price'], '10')
        before = self.path.read_bytes()
        self.assertFalse(ledger.correct_confirmations(self.path,
            {'001': {'price': 'inferred', 'time': 'inferred', 'fee': 'inferred'}}, '审计'))
        self.assertEqual(self.path.read_bytes(), before)

    def test_confirmed_sell_price_does_not_confirm_time(self):
        ledger.record(self.path, self.trade())
        ledger.record(self.path, self.trade(id='002', side='sell', price='12'))
        ledger.correct_confirmations(self.path, {'002': {'time': 'inferred'}}, '审计')
        sell = ledger.load(self.path)['trades'][1]
        self.assertEqual(sell['price'], '12')
        self.assertIsNone(sell['time'])
        self.assertEqual(ledger.load_state(self.path)['summary']['positions'], [])
        ledger.atomic_text(ledger.kline_path(self.path), '{ bad json')
        self.assertEqual(ledger.load_kline(self.path)['series'], {})

    def test_quantity_confirmation_never_confirms_supplied_estimates(self):
        raw=self.trade(confirmation={'quantity':'confirmed'},note='只确认份额，价格与时分暂记，费用未知')
        trade=ledger.validate_trade(raw)
        for key in ('price','time','fee'):self.assertIsNone(trade[key])

    def test_pending_preserves_partial_fill_counts(self):
        ledger.pending(self.path,[dict(id='p',time=ledger.now(),code='510300',exchange='SH',name='沪深300ETF',
                         price='10',quantity=1000,filled_quantity=300,remaining_quantity=700,status='partialFilled')])
        order=ledger.load(self.path)['pending_orders'][0]
        self.assertEqual(order['filled_quantity'],300)
        self.assertEqual(order['remaining_quantity'],700)
        with self.assertRaises(ValueError):
            ledger.validate_pending(dict(order,remaining_quantity=900))

    def test_revoke_and_replace_invalidate_affected_nav(self):
        ledger.record(self.path,self.trade(fee='100',quantity=1000))
        core.observe_account(self.path)
        ledger.revoke(self.path,'001','误入账')
        core.observe_account(self.path)
        points=ledger.load_state(self.path)['nav']['observations']
        old=[p for p in points if p['total_assets']=='999900.00']
        self.assertTrue(old)
        self.assertTrue(all(p.get('valid') is False for p in old))
        self.assertTrue(all(p.get('invalid_reason') for p in old))


if __name__ == '__main__':
    unittest.main()
