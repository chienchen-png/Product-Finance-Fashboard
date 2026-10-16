"""独立审阅问题的离线回归；只操作临时数据。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码'))
from datetime import datetime
import tempfile
import unittest
from unittest.mock import patch
import 账户核心 as core
import 账户台账 as ledger
import 市场同步 as market
from 数据契约 import dataset
from 数据源 import 公共行情 as public


class ReviewRegressionTests(unittest.TestCase):
    def test_account_uses_provider_time(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'账户.json';ledger.init(p,started='2026-01-01T00:00:00+08:00')
            ledger.record(p,dict(id='x',time='2026-10-10T10:00:00+08:00',code='510300',exchange='SH',name='ETF',side='buy',quantity=100,price='4',fee='0',confirmation=dict(quantity='confirmed',price='confirmed',time='confirmed',fee='confirmed')))
            q=dict(price='4.242',requested_at='2026-10-15T10:10:00+08:00',source_as_of='2026-10-14T15:00:00+08:00')
            row=core.calculate(core.load_account(p),{'SH:510300':q},at=datetime.fromisoformat('2026-10-15T10:10:00+08:00'))['positions'][0]
            self.assertFalse(row['quote_fresh'])
            self.assertEqual(row['quote_state'],'stale')

    def test_cli_cannot_replay_compacted_import_id(self):
        import 账户录入 as entry
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'账户.json';ledger.init(p)
            row=dict(id='x',time=None,code='510300',exchange='SH',name='ETF',side='buy',quantity=100,price='4',fee='0')
            entry.commit_import(p,{'kind':'trades','rows':[row]},core.account_revision(core.load_account(p)))
            ledger.reconcile(p,dict(id='r',summary=dict(total_assets='1000000',market_value='400',available_cash='999600',daily_profit='0',unrealized_profit='0'),positions=[dict(code='510300',exchange='SH',name='ETF',quantity=100,average_cost='4',price='4')]))
            ledger.compact(p);before=p.read_bytes()
            with self.assertRaises(ValueError):ledger.record(p,dict(row,confirmation=dict(quantity='confirmed',price='confirmed',fee='confirmed')))
            self.assertEqual(before,p.read_bytes())

    def test_intraday_bar_closes_at_its_end_and_us_midday_does_not_close(self):
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return cls.fromisoformat('2026-10-15T10:10:00+08:00').astimezone(tz)
        raw={'data':{'sh510300':{'m5':[['202610150935','4','4.2','4.3','3.9','100']]}}}
        with patch.object(public,'get_json',return_value=raw),patch.object(public,'datetime',Clock):
            d=public.fetch('kline',dict(symbol='SH:510300',period='m5',adjustment='raw',count=120))
        self.assertTrue(d['data'][0]['closed'])
        class USClock(datetime):
            @classmethod
            def now(cls,tz=None):return cls.fromisoformat('2026-10-16T00:30:00+08:00').astimezone(tz)
        raw={'data':{'usNDX':{'day':[['2026-10-15','30000','29900','30100','29800','100']]}}}
        with patch.object(public,'get_json',return_value=raw),patch.object(public,'datetime',USClock):
            d=public.fetch('kline',dict(symbol='INDEX:NDX',period='day',adjustment='raw',count=120))
        self.assertFalse(d['data'][0]['closed'])
        self.assertEqual(d['timezone'],'America/New_York')
        self.assertEqual(market.legacy_series(d)['currency'],'USD')

    def test_kline_only_has_one_cache_and_failures_reach_read_model(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'账户.json';ledger.init(p)
            ds=dataset('kline',[dict(time='2026-10-14',open='4',close='4',high='4',low='4',volume=None,amount=None,closed=True)],'test',symbol='SH:510300',period='day',adjustment='raw')
            engine=market.Collector(p)
            with patch.object(market.public,'fetch',return_value=ds):
                engine.update_section('kline:SH:510300:day:raw',lambda:engine.kline('SH:510300'),True)
            raw=core.read_json(market.market_path(p),{'sections':{}})
            self.assertNotIn('kline:SH:510300:day:raw',raw['sections'])
            def fail():raise OSError('offline')
            engine.update_section('kline:SH:510300:day:raw',fail,True)
            self.assertEqual(core.load_cache(p)['series']['SH:510300']['day']['status'],'stale')

    def test_total_on_demand_symbols_are_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'账户.json';ledger.init(p);engine=market.Collector(p)
            for i in range(41):engine.queue(f'kline:SH:{600000+i}:day:raw')
            with self.assertRaises(ValueError):engine.queue('kline:SH:601000:day:raw')

    def test_china_closed_does_not_block_us_jobs_or_final_china_bar(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'账户.json';ledger.init(p);engine=market.Collector(p,clock=lambda:1000)
            rows=[dict(symbol='INDEX:NDX',product_type='index'),dict(symbol='SH:510300',product_type='holding')]
            engine.tasks={k:dict(due=0,failures=0,retry_at=0,session_state='open',session_key='2026-10-14') for k in
                ('kline:INDEX:NDX:day:raw','kline:SH:510300:day:raw','kline:SH:510300:m5:raw')}
            calls=[]
            def get(symbol,period,adjustment):
                calls.append(symbol);return dataset('kline',[],'test')
            with patch.object(market,'tracked_products',return_value=rows),patch.object(engine,'kline',side_effect=get),patch.object(market,'market_state',side_effect=lambda s=None:'open' if s=='INDEX:NDX' else 'closed'):
                engine.run(('kline',))
            self.assertIn('INDEX:NDX',calls)
            self.assertIn('SH:510300',calls)

    def test_kline_revision_changes_when_only_kline_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'账户.json';ledger.init(p)
            before=core.view_model(p)
            cache=core.load_cache(p);cache['series']={'SH:510300':{'day':{'bars':[['2026-10-14','4','4','4','4','1']]}}}
            # 不改变任何updated_at字段，模拟独立K线提交。
            core.write_json(core.cache_path(p),cache)
            self.assertNotEqual(before['kline_revision'],core.view_model(p)['kline_revision'])

    def test_overview_failure_is_not_masked_by_recent_timestamp(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'账户.json';ledger.init(p)
            market._store_section(p,'overview',dataset('overview',[dict(symbol='SH:510300',price='4',source_as_of=core.now())],'test',status='stale'))
            self.assertEqual(market.read_section(p,'overview')['data'][0]['status'],'stale')

    def test_legacy_overseas_cache_cannot_keep_china_currency_or_close_clock(self):
        import 数据契约 as contract
        meta={'currency':'CNY','timezone':'Asia/Shanghai','normalized':{'symbol':'INDEX:NDX','period':'day',
              'data':[dict(time='2026-10-15',closed=True,currency='CNY')]}}
        result=contract.normalize_cached_series('INDEX:NDX',meta,datetime.fromisoformat('2026-10-16T00:30:00+08:00'))
        self.assertEqual(result['currency'],'USD')
        self.assertFalse(result['normalized']['data'][0]['closed'])


if __name__=='__main__':unittest.main()
