import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码'))
import importlib
import tempfile
import unittest
from unittest.mock import patch
from collections import Counter
from urllib.error import HTTPError
from datetime import datetime
import 账户核心 as core
import 账户台账 as ledger
from 数据契约 import dataset


class MarketScheduleTests(unittest.TestCase):
    def test_kline_permission_failure_persists_and_retries_only_when_requested(self):
        market=importlib.import_module('市场同步')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'账户记录/比赛账户.json';ledger.init(path);engine=market.Collector(path)
            def denied():raise HTTPError('https://example.invalid',403,'Forbidden',None,None)
            engine.update_section('kline:SH:600010:day:raw',denied,True)
            self.assertEqual(engine.kline_state('SH:600010')['kind'],'permission')
            restarted=market.Collector(path)
            calls=[]
            restarted.update_section('kline:SH:600010:day:raw',lambda:calls.append(1))
            self.assertEqual(calls,[])
            # 用户主动刷新可重新尝试；不能将普通网络失败误写为权限问题。
            def offline():raise ConnectionError('offline')
            restarted.update_section('kline:SH:600010:day:raw',offline,True)
            self.assertEqual(restarted.kline_state('SH:600010')['kind'],'network')

    def test_prefetch_persists_reuses_and_refreshes_rank_klines(self):
        market=importlib.import_module('市场同步')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'账户记录/比赛账户.json';ledger.init(path)
            facts=path.read_bytes();engine=market.Collector(path);calls=Counter()
            def fetch(kind,params):
                self.assertEqual(kind,'kline')
                key=(params['symbol'],params['period']);calls[key]+=1
                day='2026-10-14' if calls[key]==1 else '2026-10-15'
                stamp=day if params['period']=='day' else day+' 10:00'
                return dataset('kline',[dict(time=stamp,open='4',close='4.1',high='4.2',low='3.9',
                    amount=None,volume=None,closed=True)],'test',symbol=params['symbol'],period=params['period'],adjustment='raw')
            engine.prefetch(['SH:600010','SH:600010','FX:USDCNY'])
            self.assertEqual(engine._requests,{'kline:SH:600010:day:raw','kline:SH:600010:m5:raw'})
            with patch.object(market.public,'fetch',side_effect=fetch):
                engine.run(('kline',))
                self.assertIn('day',core.load_cache(path)['series']['SH:600010'])
                self.assertIn('m5',core.load_cache(path)['series']['SH:600010'])
                engine.prefetch(['SH:600010'])
                self.assertFalse(engine._requests,'重复读取榜单不得反复排队下载')
                engine.run(('kline',),force=True)
                self.assertEqual(calls[('SH:600010','day')],2)
                self.assertEqual(len(core.load_cache(path)['series']['SH:600010']['day']['bars']),2)
            restarted=market.Collector(path)
            self.assertIn('SH:600010',restarted._demand)
            restarted.prefetch(['SH:600010'])
            self.assertFalse(restarted._requests,'重启后的磁盘缓存也应直接复用')
            self.assertEqual(path.read_bytes(),facts)

    def test_prefetch_evicts_cold_products_with_bounded_storage(self):
        market=importlib.import_module('市场同步')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'账户记录/比赛账户.json';ledger.init(path);engine=market.Collector(path)
            engine.prefetch([f'SH:{600000+i}' for i in range(30)])
            engine.prefetch([f'SH:{601000+i}' for i in range(20)])
            tracked={r['symbol'] for r in market.tracked_products(path)}
            self.assertLessEqual(len(tracked|set(engine._demand)),50)
            self.assertTrue({f'SH:{601000+i}' for i in range(20)}<=set(engine._demand))

    def test_updates_to_separate_sections_do_not_lose_each_other(self):
        market=importlib.import_module('市场同步')
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'账户记录/比赛账户.json';ledger.init(p)
            engine=market.Collector(p)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures=[pool.submit(engine.update_section,k,lambda x=k:dataset(x,[x],'test'),True) for k in ('news','flows')]
                for f in futures:f.result()
            self.assertEqual(market.read_section(p,'news')['data'],['news'])
            self.assertEqual(market.read_section(p,'flows')['data'],['flows'])

    def test_failure_keeps_last_good_and_circuit_opens(self):
        market=importlib.import_module('市场同步')
        clock=[0.]
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'账户记录/比赛账户.json';ledger.init(p)
            engine=market.Collector(p,clock=lambda:clock[0])
            good=dataset('news',[{'id':'x'}],'test',source_as_of=core.now())
            engine.update_section('news',lambda:good,True)
            def fail():raise OSError('network')
            for _ in range(3):
                engine.update_section('news',fail,True);clock[0]+=1
            value=market.read_section(p.parent.parent,'news')
            self.assertEqual(value['data'],[{'id':'x'}])
            self.assertEqual(value['status'],'stale')
            self.assertGreater(engine.tasks['news']['retry_at'],clock[0]+800)
            calls=[]
            engine.update_section('news',lambda:calls.append(1),True)
            self.assertEqual(calls,[])

    def test_empty_account_has_market_benchmarks_and_tracking_is_bounded(self):
        market=importlib.import_module('市场同步')
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'账户记录/比赛账户.json';ledger.init(p)
            tracked=market.tracked_products(p)
            self.assertIn('INDEX:NDX',[r['symbol'] for r in tracked])
            before=p.read_bytes()
            engine=market.Collector(p)
            engine.update_section('news',lambda:dataset('news',[],'test'),True)
            self.assertEqual(before,p.read_bytes())


if __name__=='__main__':unittest.main()
