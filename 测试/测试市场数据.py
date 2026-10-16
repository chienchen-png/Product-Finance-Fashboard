"""真实字段样例契约：拒绝价量精度丢失和数据来源混接。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码'))
import importlib
import unittest
from 数据契约 import dataset, merge_series


class MarketDataTests(unittest.TestCase):
    def test_tencent_cn_price_precision_and_ratio(self):
        source=importlib.import_module('数据源.公共行情')
        cells=['']*50
        for i,v in {1:'沪深300ETF',2:'510300',3:'4.242',4:'4.294',5:'4.245',6:'15787695',
                    30:'20261015161442',32:'-1.21',33:'4.250',34:'4.187',37:'666478.08'}.items(): cells[i]=v
        result=source.parse_tencent('v_sh510300="'+'~'.join(cells)+'";',['SH:510300'])
        q=result['SH:510300']
        self.assertEqual(q['price'],'4.242')
        self.assertEqual(q['change_pct'],'-0.0121')
        self.assertEqual(q['volume'],'1578769500')
        self.assertEqual(q['source_as_of'],'2026-10-15T16:14:42+08:00')

    def test_disclosed_nav_keeps_date_and_is_not_iopv(self):
        source=importlib.import_module('数据源.东方财富')
        from unittest.mock import patch
        raw={'Data':{'LSJZList':[{'FSRQ':'2026-10-14','DWJZ':'2.0067','LJJZ':'10.0335'}]}}
        with patch.object(source,'get_json',return_value=raw):
            ds=source.fetch('nav',{'symbol':'SH:513100'})
        self.assertEqual(ds['data'][0]['unit_nav'],'2.0067')
        self.assertEqual(ds['data'][0]['date'],'2026-10-14')
        self.assertEqual(ds['source_time_kind'],'disclosure_date')
        with self.assertRaises(ValueError):source.fetch('kline',{'symbol':'SH:513100'})
    def test_source_switch_replaces_whole_series(self):
        a=dataset('kline',[dict(time='2026-10-14',close='1')],'a',adjustment='raw',precision=3)
        b=dataset('kline',[dict(time='2026-10-15',close='2')],'b',adjustment='raw',precision=3)
        self.assertEqual([r['time'] for r in merge_series(a,b,400)['data']],['2026-10-15'])

    def test_news_drops_script_and_unsafe_links(self):
        source=importlib.import_module('数据源.公共行情')
        raw={'result':{'data':{'feed':{'list':[dict(id=1,rich_text='<script>bad()</script><b>公告</b>',
           create_time='2026-10-15 20:26:52',docurl='javascript:alert(1)',user={'name':'private'})]}}}}
        news=source.parse_news(raw)['data'][0]
        self.assertEqual(news['title'],'公告')
        self.assertIsNone(news['url'])
        self.assertNotIn('user',news)


if __name__=='__main__':unittest.main()
