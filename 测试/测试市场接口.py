"""本机API与市场页契约：不联网、不改正式账户。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码'))
import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from urllib.error import HTTPError
from unittest.mock import patch
import 账户核心 as core
import 账户台账 as ledger
import 市场同步 as market
from 数据契约 import dataset
from 看板服务 import create_server


class MarketApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)/'账户记录/比赛账户.json'
        ledger.init(self.p)
        market._store_section(self.p,'news',dataset('news',[dict(id='1',title='测试快讯')],'test',source_as_of=core.now()))
        self.server=create_server(self.p,0,runner=lambda _: {})
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def get(self,path,headers=None):
        h={'X-Dashboard-Token':self.server.local_token};h.update(headers or {})
        return urllib.request.urlopen(urllib.request.Request(self.base+path,headers=h),timeout=4)

    def test_market_api_etag_validation_and_no_read_side_effect(self):
        before={str(p):p.read_bytes() for p in Path(self.tmp.name).rglob('*') if p.is_file()}
        with self.get('/api/market?section=news') as r:
            data=json.load(r);etag=r.headers['ETag']
        self.assertEqual(data['data'][0]['title'],'测试快讯')
        with self.assertRaises(urllib.error.HTTPError) as e:self.get('/api/market?section=news',{'If-None-Match':etag})
        self.assertEqual(e.exception.code,304)
        e.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as e:self.get('/api/market?section=../../x')
        self.assertEqual(e.exception.code,400)
        e.exception.close()
        self.assertEqual(before,{str(p):p.read_bytes() for p in Path(self.tmp.name).rglob('*') if p.is_file()})
        with self.assertRaises(urllib.error.HTTPError) as disabled:
            self.get('/api/market?section=flows')
        self.assertEqual(disabled.exception.code,400)
        disabled.exception.close()

    def test_market_page_has_two_tabs_and_no_external_scripts(self):
        with self.get('/') as r:page=r.read().decode()
        self.assertIn('id="market-page"',page)
        self.assertIn('id="account-page"',page)
        self.assertNotIn('<script src="http',page)

    def test_reading_rank_preheats_in_memory_without_modifying_account(self):
        market._store_section(self.p,'ranks:etf:up',dataset('ranks',[
            dict(symbol='SH:510300',name='ETF',price='4')],'test'))
        before=self.p.read_bytes()
        with self.get('/api/market?section=ranks&product_type=etf&sort=up') as r:json.load(r)
        engine=market.collector(self.p)
        self.assertIn('kline:SH:510300:day:raw',engine._requests)
        self.assertIn('kline:SH:510300:m5:raw',engine._requests)
        requests=set(engine._requests)
        with self.get('/api/market?section=ranks&product_type=etf&sort=up') as r:json.load(r)
        self.assertEqual(engine._requests,requests)
        self.assertEqual(self.p.read_bytes(),before)

    def test_failed_and_unsupported_kline_end_loading_without_requeue(self):
        engine=market.collector(self.p)
        def denied():raise HTTPError('https://example.invalid',403,'Forbidden',None,None)
        engine.update_section('kline:SH:600010:day:raw',denied,True)
        before=self.p.read_bytes()
        for _ in range(2):
            with self.get('/api/kline?symbol=SH:600010') as response:value=json.load(response)
            self.assertEqual(value['status'],'failed')
            self.assertEqual(value['kind'],'permission')
            self.assertFalse(value['pending'])
            self.assertIn('权限受限',value['message'])
        with self.get('/api/kline?symbol=FX:USDCNY') as response:value=json.load(response)
        self.assertEqual(value['status'],'unsupported')
        self.assertFalse(value['pending'])
        self.assertFalse(engine._requests)
        self.assertEqual(self.p.read_bytes(),before)

    def test_overview_flags_inaccessible_cards_but_keeps_usable_cached_data(self):
        market._store_section(self.p,'overview',dataset('overview',[
            dict(symbol='FX:USDCNY',price='7'),dict(symbol='INDEX:NDX',price='20000')],'test'))
        engine=market.collector(self.p)
        def denied():raise HTTPError('https://example.invalid',403,'Forbidden',None,None)
        engine.update_section('kline:INDEX:NDX:day:raw',denied,True)
        with self.get('/api/market?section=overview') as response:value=json.load(response)
        self.assertFalse(any(row['chart_available'] for row in value['data']))

    def post(self,route,payload,extra=None):
        h={'X-Dashboard-Token':self.server.local_token,'Content-Type':'application/json',
           'Origin':self.base};h.update(extra or {})
        req=urllib.request.Request(self.base+route,data=json.dumps(payload).encode(),headers=h)
        return urllib.request.urlopen(req,timeout=4)

    def test_import_preview_commit_token_and_replay(self):
        payload={'kind':'trades','rows':[dict(id='x',code='510300',exchange='SH',name='ETF',side='buy',
            quantity=100,price='4.242',fee=None,time=None)]}
        before=self.p.read_bytes()
        with self.post('/api/import/preview',payload) as r:preview=json.load(r)
        self.assertEqual(before,self.p.read_bytes())
        request=dict(token=preview['token'],expected_revision=preview['revision'])
        with self.post('/api/import/commit',request) as r:result=json.load(r)
        self.assertEqual(len(core.load_account(self.p)['trades']),1)
        saved=self.p.read_bytes()
        with self.post('/api/import/commit',request) as r:self.assertEqual(json.load(r),result)
        self.assertEqual(saved,self.p.read_bytes())
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.post('/api/import/preview',payload,{'Origin':'https://example.com'})
        self.assertEqual(e.exception.code,403);e.exception.close()

    def test_announcement_rejects_other_company(self):
        from 数据源 import 巨潮资讯 as cn
        responses=[[dict(code='601688',orgId='org')],{'announcements':[dict(secCode='000001',orgId='other')]}]
        with patch.object(cn,'get_json',side_effect=responses):
            self.assertEqual(cn.fetch('announcements',{'symbol':'SH:601688'})['data'],[])


if __name__=='__main__':unittest.main()
