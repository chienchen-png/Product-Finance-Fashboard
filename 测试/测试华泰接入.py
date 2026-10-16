"""华泰主源、回退、时点隔离和共享研究资料；不访问外部接口。"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码'))
import json
import os
import tempfile
import unittest
from unittest.mock import patch
import 账户台账 as ledger
import 账户核心 as core
import 市场同步 as market
import 华泰资料 as research
from 数据源 import 华泰 as ht,公共行情 as public


class HuataiTests(unittest.TestCase):
    def setUp(self):
        self.raw={'ok':True,'data':dict(stockName='测试ETF',currentPrice=1.219,prevClose=1.212,change=.58,
            limitUp=1.333,limitDown=1.091,bidPrice1=1.219,askPrice1=1.22,isSuspended=False)}
        self.reference=public.quote('SH:512890','测试ETF','1.219')
        self.reference.update(source='腾讯网页行情',source_as_of=core.now(),prev_close='1.212',amount='2000',amount_unit='CNY')

    def test_key_precedence_env_over_program_config_over_user_config(self):
        """密钥优先级：环境变量 > 程序目录配置.json > 用户目录.htsc-skills/config。"""
        with tempfile.TemporaryDirectory() as folder:
            配置=Path(folder)/'配置.json';配置.write_text(json.dumps({'HT_APIKEY':'程序密钥'}),encoding='utf-8')
            用户配置=Path(folder)/'.htsc-skills/config';用户配置.parent.mkdir();用户配置.write_text('HT_APIKEY=用户密钥\n',encoding='utf-8')
            空配置=Path(folder)/'没有.json'
            with patch.object(Path,'home',return_value=Path(folder)):
                with patch.object(ht,'程序配置',return_value=配置),patch.dict(os.environ,{'HT_APIKEY':'环境密钥'}):
                    self.assertEqual(ht.key(),'环境密钥')
                with patch.object(ht,'程序配置',return_value=配置),patch.dict(os.environ,{'HT_APIKEY':''}):
                    self.assertEqual(ht.key(),'程序密钥')
                with patch.object(ht,'程序配置',return_value=空配置),patch.dict(os.environ,{'HT_APIKEY':''}):
                    self.assertEqual(ht.key(),'用户密钥')
                with patch.object(ht,'程序配置',return_value=空配置),patch.dict(os.environ,{'HT_APIKEY':''}):
                    用户配置.unlink()
                    self.assertEqual(ht.key(),'')

    def test_primary_price_has_no_invented_market_time_and_keeps_field_provenance(self):
        row=ht.normalized('SH:512890',self.raw,self.reference)
        self.assertEqual(row['source'],'华泰Skill getQuote')
        self.assertIsNone(row['source_as_of'])
        self.assertEqual(row['change_pct'],'0.0058')
        self.assertTrue(row['reference_quote']['matches_price'])
        self.assertEqual(row['source_fields']['amount'],'腾讯网页行情')
        self.assertEqual(row['source_fields']['price'],'华泰Skill getQuote')
        self.assertIsNone(row['source_fields']['source_as_of'])

    def test_router_prefers_huatai_and_falls_back_per_product(self):
        with patch.object(ht,'fetch',return_value=({'SH:512890':ht.normalized('SH:512890',self.raw)},dict(status='partial'))),patch.object(public,'_fetch_public_quotes',return_value={'SH:512890':self.reference,'SH:000001':dict(self.reference,symbol='SH:000001')}):
            rows=public.fetch_quotes(['SH:512890','SH:000001'])
        self.assertTrue(rows['SH:512890']['routing']['used_primary'])
        self.assertFalse(rows['SH:000001']['routing']['used_primary'])
        self.assertEqual(rows['SH:000001']['source'],'腾讯网页行情')

    def test_public_outage_does_not_block_successful_primary(self):
        with patch.object(ht,'fetch',return_value=({'SH:512890':ht.normalized('SH:512890',self.raw)},dict(status='ok'))),patch.object(public,'_fetch_public_quotes',side_effect=OSError):
            self.assertEqual(public.fetch_quotes(['SH:512890'])['SH:512890']['price'],'1.219')

    def test_no_key_preserves_existing_sources(self):
        with patch.object(ht,'configured',return_value=False),patch.object(public,'_fetch_public_quotes',return_value={'SH:512890':self.reference}),patch.object(ht,'_post') as post:
            row=public.fetch_quotes(['SH:512890'])['SH:512890'];post.assert_not_called()
        self.assertEqual(row['source'],'腾讯网页行情')
        self.assertEqual(row['routing']['primary_status'],'not_configured')

    def test_readonly_request_does_not_follow_redirect_or_implement_orders(self):
        from types import SimpleNamespace
        with patch('requests.post',return_value=SimpleNamespace(status_code=302)) as post:
            self.assertFalse(ht._post('SH:512890','unit-key')['ok'])
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        self.assertNotIn('submitOrder',ht.__dict__)

    def test_shared_research_keeps_failed_old_content_and_never_updates_account(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'账户记录/比赛账户.json';ledger.init(path);before=path.read_bytes()
            old=dict(id='events',title='旧资讯',answer='旧资料',retrieved_at=core.now(),content_hash='old')
            market._store_section(path,'huatai',market.dataset('huatai',[old],'test'))
            def fake(kind,query):
                if kind=='events':raise ValueError('unavailable')
                return dict(id=kind,title=kind,answer='| 项目 | 数值 |\n| --- | --- |\n| A | 1 |',retrieved_at=core.now(),verification='supplier_ai_unverified',content_hash=kind)
            with patch.object(research,'fetch',side_effect=fake):value=research.run(path)
            self.assertFalse(value['pending']);self.assertEqual(value['status'],'partial')
            self.assertEqual(next(r['answer'] for r in value['data'] if r['id']=='events'),'旧资料')
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(market.read_section(path,'huatai')['data'],value['data'])

    def test_manual_refresh_bypasses_closed_cache_and_unknown_time_is_not_final(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'账户记录/比赛账户.json';ledger.init(path)
            for stamp,force in ((core.now(),True),(None,False)):
                quote=dict(self.reference,source_as_of=stamp,retrieved_at=core.now())
                cache=core.load_cache(path);cache['quotes']={'SH:512890':{'normalized_quote':quote}}
                core.save_cache(path,cache)
                with patch.object(market,'tracked_products',return_value=[dict(symbol='SH:512890',name='测试ETF',product_type='watch')]),patch.object(market,'market_state',return_value='closed'),patch.object(market.public,'fetch_quotes',return_value={'SH:512890':self.reference}) as fetch:
                    market.Collector(path)._quotes(force)
                fetch.assert_called_once()


if __name__=='__main__':unittest.main()
