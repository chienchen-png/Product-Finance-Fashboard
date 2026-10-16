import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码'))
"""用手机对账基线恢复已知资产；不把显示均价或差额伪造成成交与费用。"""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest

import 账户核心 as core
import 账户台账 as ledger


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / '账户.json'
        ledger.init(self.path, started='2026-10-10T00:00:00+08:00')
        self.rows = [('512890',90000,'1.229','1.219'),('513100',40000,'2.331','2.321'),
                     ('510300',15000,'4.249','4.242'),('518880',5000,'8.503','8.472')]
        for code,qty,_,_ in self.rows:
            ledger.record(self.path, dict(id=code, time=None, trade_date=core.now()[:10], code=code,
                exchange='SH',name=code,side='buy',quantity=qty,price=None,fee=None,
                confirmation={'quantity':'confirmed'}))
        self.report = {'id':'phone-1','reported_at':None,
            'summary':{'total_assets':'997291.92','market_value':'307910.00','available_cash':'689381.92',
                       'daily_profit':'-5755.00','unrealized_profit':'-2213.01'},
            'positions':[dict(key='SH:'+c,code=c,exchange='SH',name=c,quantity=q,
                              average_cost=a,price=p) for c,q,a,p in self.rows]}

    def tearDown(self):
        self.folder.cleanup()

    def test_report_restores_known_totals_without_inventing_trade_fees(self):
        ledger.reconcile(self.path,self.report)
        core.observe_account(self.path)
        ledger.render(self.path)
        state=ledger.load_state(self.path); s=state['summary']
        self.assertEqual(s['cash'],'689381.92')
        self.assertEqual(s['total_assets'],'997291.92')
        self.assertEqual(s['market_value'],'307910.00')
        self.assertEqual(s['daily_profit'],'-5755.00')
        self.assertEqual(s['unrealized_profit'],'-2213.01')
        self.assertEqual(s['profit'],'-2708.08')
        self.assertEqual(s['return_pct'],'-0.2708')
        self.assertIsNone(s['realized_profit'])  # 汇总差值不冒充手机已实现盈亏
        self.assertEqual(s['positions'][0]['average_cost'],'1.2290')
        self.assertTrue(all(t['price'] is None and t['fee'] is None for t in state['account']['trades']))
        self.assertTrue(state['nav']['observations'][-1]['valid'])
        self.assertEqual(state['nav']['observations'][-1]['total_assets'],'997291.92')
        self.assertIn('997291.92',self.path.with_name('比赛账户看板.html').read_text(encoding='utf-8'))

    def test_conflicting_row_prices_are_preserved_and_reconciled_explicitly(self):
        ledger.reconcile(self.path,self.report)
        s=ledger.load_state(self.path)['summary']; r=s['reconciliation']
        self.assertEqual(s['positions'][0]['price'],'1.219')
        self.assertEqual(r['reported_row_market_value'],'308540.00')
        self.assertEqual(r['market_value_difference'],'630.00')
        self.assertEqual(r['display_cost_difference'],'23.01')
        self.assertTrue(r['using_reported_totals'])

    def test_new_quotes_revalue_from_confirmed_cash_not_old_unknown_fees(self):
        ledger.reconcile(self.path,self.report)
        report=ledger.load(self.path)['reconciliations'][-1]
        stamp=(datetime.fromisoformat(report['recorded_at'])+timedelta(seconds=1)).isoformat()
        cache=core.load_cache(self.path)
        cache['quotes']={'SH:'+c:{'price':('1.212' if c=='512890' else p),
                         'requested_at':stamp,'source':'测试新行情'} for c,_,_,p in self.rows}
        core.save_cache(self.path,cache)
        s=ledger.load_state(self.path)['summary']
        self.assertEqual(s['cash'],'689381.92')
        self.assertEqual(s['market_value'],'307910.00')
        self.assertEqual(s['total_assets'],'997291.92')
        self.assertEqual(s['unrealized_profit'],'-2213.01')
        self.assertFalse(s['reconciliation']['using_reported_totals'])

    def test_later_fill_rolls_cash_forward_once_and_does_not_reuse_old_header(self):
        ledger.reconcile(self.path,self.report)
        ledger.record(self.path,dict(id='sell',time=None,trade_date=core.now()[:10],code='512890',exchange='SH',
            name='红利',side='sell',quantity=100,price='1.22',fee='1',
            confirmation={'quantity':'confirmed','price':'confirmed','fee':'confirmed'}))
        s=ledger.load_state(self.path)['summary']
        self.assertEqual(s['cash'],'689502.92')
        self.assertEqual(s['positions'][0]['quantity'],89900)
        self.assertFalse(s['reconciliation']['using_reported_totals'])
        self.assertIsNone(s['realized_profit'])  # 未分配的成本差额不按比例臆造

    def test_report_cannot_survive_covered_trade_mutation_or_future_cutoff(self):
        ledger.reconcile(self.path,self.report)
        account=ledger.load(self.path)
        self.assertIsNone(core.calculate(account,at=datetime(2026,10,10,tzinfo=core.TZ))['cash'])
        ledger.revoke(self.path,'512890','数量误录')
        self.assertIsNone(ledger.load_state(self.path)['summary']['cash'])

    def test_invalid_and_duplicate_reports_do_not_overwrite_facts(self):
        baseline=self.path.read_bytes()
        for field,value in [('total_assets','1'),('available_cash','NaN')]:
            bad=copy.deepcopy(self.report);bad['summary'][field]=value
            with self.assertRaises(ValueError):ledger.reconcile(self.path,bad)
            self.assertEqual(self.path.read_bytes(),baseline)
        bad=copy.deepcopy(self.report);bad['positions'][0]['quantity']=1
        with self.assertRaises(ValueError):ledger.reconcile(self.path,bad)
        ledger.reconcile(self.path,self.report); saved=self.path.read_bytes()
        with self.assertRaises(ValueError):ledger.reconcile(self.path,self.report)
        self.assertEqual(self.path.read_bytes(),saved)

    def test_compact_keeps_current_account_without_trade_history(self):
        corrected=copy.deepcopy(self.report)
        corrected['positions'][0]['price']='1.212'
        ledger.reconcile(self.path,corrected)
        before=ledger.load_state(self.path)['summary']
        ledger.compact(self.path)
        facts=ledger.load(self.path)
        after=ledger.load_state(self.path)['summary']
        self.assertEqual(facts['trades'],[])
        self.assertEqual(facts.get('corrections',[]),[])
        self.assertEqual(len(facts['reconciliations']),1)
        self.assertEqual(facts['reconciliations'][0]['covered_trade_count'],0)
        self.assertEqual(facts['reconciliations'][0]['trade_basis'],core.trade_digest([]))
        for field in ('cash','market_value','total_assets','profit','return_pct','daily_profit','unrealized_profit'):
            self.assertEqual(after[field],before[field])
        self.assertEqual([(p['key'],p['quantity'],p['price']) for p in after['positions']],
                         [(p['key'],p['quantity'],p['price']) for p in before['positions']])

    def test_compact_refuses_unreconciled_new_fill(self):
        ledger.reconcile(self.path,self.report)
        ledger.record(self.path,dict(id='new',time=None,trade_date=core.now()[:10],code='512890',
            exchange='SH',name='红利',side='sell',quantity=100,price='1.22',fee='1',
            confirmation={'quantity':'confirmed','price':'confirmed','fee':'confirmed'}))
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):ledger.compact(self.path)
        self.assertEqual(self.path.read_bytes(),before)


class OpeningBaselineTests(unittest.TestCase):
    """队友带着既有持仓入场：无成交、无历史对账时可用手机持仓直接开账。"""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / '账户.json'
        ledger.init(self.path, started='2026-10-10T00:00:00+08:00')
        self.report = {'id':'opening','reported_at':None,
            'summary':{'total_assets':'1050000.00','market_value':'600000.00','available_cash':'450000.00',
                       'daily_profit':'0.00','unrealized_profit':'20000.00'},
            'positions':[dict(key='SH:510300',code='510300',exchange='SH',name='沪深300ETF',
                              quantity=100000,average_cost='4.0000',price='4.2000',available_quantity=100000),
                         dict(key='SH:512890',code='512890',exchange='SH',name='红利低波ETF',
                              quantity=150000,average_cost='1.1000',price='1.2000')]}

    def tearDown(self):
        self.folder.cleanup()

    def test_opening_baseline_accepts_existing_holdings(self):
        report = ledger.reconcile(self.path, self.report)
        self.assertTrue(report.get('opening'))
        state = ledger.load_state(self.path); s = state['summary']
        self.assertEqual(s['cash'],'450000.00')
        self.assertEqual(s['market_value'],'600000.00')
        self.assertEqual(s['total_assets'],'1050000.00')
        self.assertEqual(s['profit'],'50000.00')
        self.assertEqual(s['return_pct'],'5.0000')
        self.assertEqual([(p['key'],p['quantity']) for p in s['positions']],
                         [('SH:510300',100000),('SH:512890',150000)])
        self.assertEqual(s['positions'][0]['available_quantity'],100000)
        self.assertIsNone(s['positions'][1]['available_quantity'])
        self.assertEqual(state['account']['trades'],[])

    def test_after_opening_baseline_holdings_must_match_confirmed_trades(self):
        ledger.reconcile(self.path, self.report)
        bad = copy.deepcopy(self.report); bad['id']='phone-2'
        bad['positions'][0]['quantity'] = 99000
        bad['summary'].update(market_value='596000.00', total_assets='1046000.00')
        with self.assertRaises(ValueError):
            ledger.reconcile(self.path, bad)

    def test_optional_profit_fields_remain_unknown(self):
        report=copy.deepcopy(self.report)
        report['summary'].pop('daily_profit')
        report['summary']['unrealized_profit']=''
        ledger.reconcile(self.path,report)
        summary=ledger.load_state(self.path)['summary']
        self.assertEqual(summary['total_assets'],'1050000.00')
        self.assertIsNone(summary['daily_profit'])
        self.assertIsNone(summary['unrealized_profit'])
        self.assertIsNone(summary['reconciliation']['display_cost_difference'])

    def test_opening_does_not_allow_replaying_covered_old_trade(self):
        ledger.reconcile(self.path,self.report)
        with self.assertRaisesRegex(ValueError,'早于当前手机快照'):
            ledger.record(self.path,dict(id='old',time='2026-10-10T10:00:00+08:00',code='510300',exchange='SH',
                name='ETF',side='buy',quantity=100,price='4',fee='0',confirmation=dict(quantity='confirmed',price='confirmed',fee='confirmed',time='confirmed')))


if __name__=='__main__':
    unittest.main()
