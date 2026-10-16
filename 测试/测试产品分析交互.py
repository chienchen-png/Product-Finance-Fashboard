"""产品原位分析、任务调用、跨产品隔离及无变更首页稳定性。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码'))
import tempfile
import threading
import unittest
from unittest.mock import patch
import 账户台账 as ledger
import 账户核心 as core
import 市场同步 as market
import 投研缓存 as research
from 数据契约 import dataset
from 看板服务 import create_server


class ProductTests(unittest.TestCase):
    def test_market_is_stable_and_updates_prices_without_removing_trends(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'账户记录/比赛账户.json';ledger.init(p)
            ds=dataset('overview',[dict(symbol='INDEX:NDX',name='纳斯达克100',price='20000',change_pct='.01',product_type='index')],'test')
            market._store_section(p,'overview',ds)
            c=core.load_cache(p);c['series']={'INDEX:NDX':{'day':dict(updated_at=core.now(),source='test',adjustment='raw',bars=[[f'2026-09-{i:02d}','100',str(100+i),'130','90','100'] for i in range(1,22)])}};core.save_cache(p,c)
            server=create_server(p,0,runner=lambda _:{});t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
            try:
                with sync_playwright() as driver:
                    browser=driver.chromium.launch(channel='msedge',headless=True);page=browser.new_page();page.goto(f'http://127.0.0.1:{server.server_port}/')
                    page.wait_for_function("document.querySelector('.index-trend')?.textContent.includes('20日')")
                    page.evaluate("window.firstCard=document.querySelector('.index-card');window.removed=0;new MutationObserver(ms=>{for(const m of ms)window.removed+=m.removedNodes.length}).observe(document.getElementById('index-strip'),{childList:true,subtree:true})")
                    height=page.locator('#index-strip').bounding_box()['height']
                    for _ in range(3):page.evaluate('MarketDashboard.update()')
                    self.assertTrue(page.evaluate("firstCard===document.querySelector('.index-card')"));self.assertEqual(page.evaluate('removed'),0)
                    self.assertEqual(height,page.locator('#index-strip').bounding_box()['height'])
                    ds['data'][0]['price']='20100';market._store_section(p,'overview',ds)
                    page.evaluate('MarketDashboard.update()');page.wait_for_function("document.querySelector('.index-card b').textContent.includes('20,100')")
                    self.assertEqual(height,page.locator('#index-strip').bounding_box()['height']);self.assertIn('20日',page.locator('.index-trend').inner_text())
                    browser.close()
            finally:server.shutdown();server.server_close();t.join()

    def test_first_analysis_click_generates_in_place_and_cache_is_shared(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'账户记录/比赛账户.json';ledger.init(p)
            ledger.record(p,dict(id='t',time=core.now(),code='512890',exchange='SH',name='测试ETF',side='buy',quantity=100,price='1.2',fee='0',confirmation=dict(quantity='confirmed',price='confirmed',time='confirmed',fee='confirmed')))
            market._store_section(p,'ranks:stock:up',dataset('ranks',[dict(symbol='SH:512890',name='测试ETF',price='1.2')],'test'))
            calls=[]
            def fetch(kind,query):calls.append(kind);return dict(answer='### 产品关键点\n这是一份产品分析。',retrieved_at=core.now(),source='test')
            engine=research.Engine(p,fetcher=fetch)
            server=create_server(p,0,runner=lambda _:{});t=threading.Thread(target=server.serve_forever,daemon=True);t.start();before=p.read_bytes()
            try:
                with patch.object(research,'configured',return_value=True),patch.object(research,'engine',return_value=engine),sync_playwright() as driver:
                    browser=driver.chromium.launch(channel='msedge',headless=True);page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/');page.locator('#rank-rows [data-product]').click();page.locator('#product-dialog [data-detail-tab=analysis]').click()
                    page.wait_for_selector('#product-dialog .analysis-body h3',timeout=15000)
                    self.assertEqual(calls,['product']);self.assertTrue(page.locator('#product-dialog').is_visible());self.assertEqual(page.evaluate('DashboardNavigation.active'),'market')
                    page.locator('#product-close').click();page.locator('[data-page=account]').click();page.locator('#positions .pos').click();page.locator('#positions [data-detail-tab=analysis]').click();page.wait_for_selector('#positions .analysis-body h3')
                    page.evaluate('applyData({...d})');self.assertTrue(page.locator('#positions [data-analysis-panel]').is_visible());self.assertEqual(calls,['product'])
                    def denied(*_):calls.append('failure');raise ValueError('接口权限受限')
                    engine.fetcher=denied;engine.ttl=0
                    page.locator('#positions .analysis-refresh').click();page.wait_for_function("document.querySelector('#positions .analysis-state').textContent.includes('接口权限受限')",timeout=15000)
                    self.assertIn('产品关键点',page.locator('#positions .analysis-body').inner_text())
                    page.wait_for_timeout(5500);self.assertEqual(calls,['product','failure'])
                    page.locator('[data-page=research]').click();page.wait_for_selector('#research-topic');self.assertEqual(page.locator('#research-list [data-report^="product:"]').count(),0)
                    self.assertFalse(errors,errors);browser.close()
                self.assertEqual(p.read_bytes(),before)
            finally:server.shutdown();server.server_close();t.join();engine.pool.shutdown(wait=True)


if __name__=='__main__':unittest.main()
