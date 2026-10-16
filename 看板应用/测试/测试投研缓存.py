import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码'))
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
import 账户台账 as ledger
import 账户核心 as core
import 市场同步 as market
import 投研缓存 as store


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'账户记录/比赛账户.json';ledger.init(self.path)
    def tearDown(self):self.temp.cleanup()
    def test_migration_preserves_original_and_removes_double_write(self):
        old=dict(id='events',answer='原文',content_hash='unchanged',retrieved_at=core.now(),title='旧事件')
        market._store_section(self.path,'huatai',market.dataset('huatai',[old],'test'))
        before=self.path.read_bytes();store.migrate(self.path);store.migrate(self.path)
        self.assertEqual(store.legacy(self.path)['data'][0]['content_hash'],'unchanged')
        self.assertNotIn('huatai',core.read_json(market.market_path(self.path))['sections'])
        self.assertEqual(self.path.read_bytes(),before)
    def test_job_success_ttl_reuse_and_no_body_in_index(self):
        calls=[]
        def fetch(kind,q):calls.append(kind);return dict(answer='正文',retrieved_at=core.now(),source='test')
        engine=store.Engine(self.path,fetcher=fetch)
        engine.submit('market_a');engine.pool.shutdown(wait=True)
        self.assertTrue(engine.submit('market_a')['cached']);self.assertEqual(calls,['market_a'])
        self.assertNotIn('answer',store.view(self.path)['documents'][0])
        self.assertEqual(store.view(self.path,'market_a')['document']['answer'],'正文')
    def test_failure_or_late_result_does_not_replace_previous_report(self):
        previous=dict(answer='旧正文',retrieved_at=core.now(),key='market_a:market',topic='market_a',subject={})
        store.mutate(self.path,lambda d:d['documents'].update({'market_a:market':previous}))
        times=iter([0,121]);engine=store.Engine(self.path,fetcher=lambda *_:dict(answer='迟到的新正文'),clock=lambda:next(times),budget=120)
        engine.submit('market_a');engine.pool.shutdown(wait=True)
        self.assertEqual(store.view(self.path,'market_a')['document']['answer'],'旧正文')
        self.assertEqual(store.view(self.path,'market_a')['job']['state'],'failed')
    def test_finite_queue_dedup_and_no_transaction_tools(self):
        gate=threading.Event();calls=[]
        def fetch(kind,q):calls.append(kind);gate.wait(3);return dict(answer='正文',retrieved_at=core.now())
        engine=store.Engine(self.path,fetcher=fetch)
        try:
            first=engine.submit('market_a');self.assertEqual(engine.submit('market_a')['job_id'],first['job_id'])
            for name in ('overseas','capital','events'):engine.submit(name)
            engine.submit('product','SH:512890');engine.submit('product','SH:513100')
            with self.assertRaises(ValueError):engine.submit('product','SH:518880')
            with self.assertRaises(ValueError):engine.submit('selectStock')
        finally:gate.set();engine.pool.shutdown(wait=True)
        self.assertEqual(len(calls),6)
    def test_validated_fund_view_and_parse_failure_preserve_old(self):
        raw=json.dumps(dict(code='512890',date=store.trading_date(),net_inflow_yuan=-100,definition='主力净额',source_url=None))
        e=store.Engine(self.path,fetcher=lambda *_:dict(answer=raw,retrieved_at=core.now(),source='test'))
        e.submit('fund','SH:512890');e.pool.shutdown(wait=True)
        self.assertEqual(store.funds(self.path)['data'][0]['net_inflow_yuan'],'-100')
        e=store.Engine(self.path,fetcher=lambda *_:dict(answer='无数据'),ttl=0)
        e.submit('fund','SH:512890');e.pool.shutdown(wait=True)
        self.assertEqual(store.funds(self.path)['data'][0]['net_inflow_yuan'],'-100')
        self.assertEqual(store.view(self.path,'fund','SH:512890')['job']['state'],'failed')
    def test_index_analysis_uses_market_tool_and_never_fund_endpoint(self):
        for symbol in ('SH:000001','INDEX:NDX','INDEX:HSI','FX:USDCNY','FUT:GC'):
            self.assertEqual(store.spec(self.path,'product',symbol)['provider_kind'],'product_market')
        self.assertEqual(store.spec(self.path,'product','SH:512890')['provider_kind'],'product')
        with self.assertRaises(ValueError):store.spec(self.path,'product','INDEX:UNKNOWN')
        with self.assertRaises(ValueError):store.spec(self.path,'fund','INDEX:NDX')

    def test_no_auth_or_unknown_sector_cannot_submit(self):
        with patch.object(store,'configured',return_value=False):
            with self.assertRaises(ValueError):store.Engine(self.path).submit('market_a')
        with self.assertRaises(ValueError):store.spec(self.path,'sector',sector='unknown')


if __name__=='__main__':unittest.main()
