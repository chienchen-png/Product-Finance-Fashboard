"""接入边界：研究候选不得自动成为软件数据源。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码'))
import unittest
from unittest.mock import patch
import 市场同步 as market
from 数据源 import 公共行情 as public


class EnabledFeedTests(unittest.TestCase):
    def test_unavailable_capabilities_are_not_exposed_as_enabled(self):
        caps=market.capabilities()
        self.assertFalse(caps['flows'])
        self.assertEqual(caps['sectors'],['industry'])
        self.assertEqual(caps['kline_sources'],['腾讯网页K线'])
        self.assertFalse(caps['announcements'])

    def test_industry_fields_and_real_amount_are_preserved(self):
        text='var S_Finance_bankuai_sinaindustry = {"new_blhy":"new_blhy,玻璃行业,19,14.795,-0.614,-3.9892072816695,419783255,8726514197,sz002571,0.100,10.010,0.010,德力股份"};'
        ds=public.parse_industry(text)
        row=ds['data'][0]
        self.assertEqual(row['amount'],'8726514197')
        self.assertEqual(row['member_count'],19)
        self.assertEqual(row['change_pct'],'-0.039892072816695')
        self.assertIsNone(row['main_net'])
        self.assertIsNone(ds['source_as_of'])

    def test_overseas_raw_bar_uses_working_request_and_day_field(self):
        urls=[]
        def transport(url):
            urls.append(url)
            if not url.endswith(',qfq'):raise ValueError('海外接口不接受空模式参数')
            return {'data':{'usNDX':{'day':[['2026-10-14','30000','29900','30100','29800','100']]}}}
        with patch.object(public,'get_json',side_effect=transport):
            ds=public.fetch('kline',dict(symbol='INDEX:NDX',period='day',adjustment='raw',count=120))
        self.assertEqual(ds['data'][0]['close'],'29900')
        self.assertEqual(ds['adjustment'],'raw')

    def test_minute_request_never_exceeds_verified_provider_window(self):
        def transport(url):
            if not url.endswith(',m5,,640'):raise ValueError('超过已验证窗口会被接口退回320根')
            return {'data':{'sh510300':{'m5':[['202610151500','4','4.2','4.3','3.9','100']]}}}
        with patch.object(public,'get_json',side_effect=transport):
            ds=public.fetch('kline',dict(symbol='SH:510300',period='m5',adjustment='raw',count=2400))
        self.assertEqual(len(ds['data']),1)


if __name__=='__main__':unittest.main()
