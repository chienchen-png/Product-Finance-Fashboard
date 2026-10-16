"""三页导航、迁移内容、页面布局；临时账户，仅本机请求。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码'))
import tempfile
import threading
import unittest
import 账户台账 as ledger
import 账户核心 as core
import 市场同步 as market
from 数据契约 import dataset
from 看板服务 import create_server


class ThreePageTests(unittest.TestCase):
    def test_product_analysis_reads_cache_inside_current_detail(self):
        from playwright.sync_api import sync_playwright
        import 投研缓存 as research
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'账户记录/比赛账户.json';ledger.init(path)
            market._store_section(path,'overview',dataset('overview',[dict(symbol='SH:512890',name='测试产品',price='1.2',product_type='etf')],'test'))
            research.mutate(path,lambda data:data['documents'].update({'product:SH:512890':dict(key='product:SH:512890',topic='product',title='产品诊断',subject={'symbol':'SH:512890'},answer='### 产品关键点\n<script>window.bad=1</script>\n| 指标 | 值 |\n|---|---|\n| 测试 | 1 |',content_hash='x',retrieved_at=core.now())}))
            server=create_server(path,0,runner=lambda _:{});thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with sync_playwright() as driver:
                    browser=driver.chromium.launch(channel='msedge',headless=True);page=browser.new_page();posts=[]
                    page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
                    page.goto(f'http://127.0.0.1:{server.server_port}/');page.locator('[data-product="SH:512890"]').first.click()
                    page.locator('#product-dialog [data-detail-tab=analysis]').click();page.wait_for_selector('#product-dialog .analysis-body h3')
                    self.assertTrue(page.locator('#product-dialog').is_visible());self.assertEqual(page.evaluate('DashboardNavigation.active'),'market')
                    self.assertEqual(page.locator('#product-dialog .analysis-body script').count(),0);self.assertIsNone(page.evaluate('window.bad'))
                    self.assertFalse(any('/research/refresh' in u for u in posts))
                    page.locator('#product-close').click();page.locator('[data-page=research]').click()
                    page.wait_for_selector('#research-topic');self.assertEqual(page.locator('#research-topic option[value=product]').count(),0)
                    self.assertEqual(page.locator('#research-list button').count(),0)
                    browser.close()
            finally:server.shutdown();server.server_close();thread.join()

    def test_navigation_content_and_layout(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'账户记录/比赛账户.json';ledger.init(path)
            market._store_section(path,'news',dataset('news',[dict(id='n',title='测试快讯',summary='完整快讯正文',source='test',published_at=core.now())],'test'))
            market._store_section(path,'huatai',dataset('huatai',[dict(id='events',title='既有报告',answer='### 内容\n已有研究正文',retrieved_at=core.now())],'test'))
            before=path.read_bytes();server=create_server(path,0,runner=lambda _:{});t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
            try:
                with sync_playwright() as driver:
                    browser=driver.chromium.launch(channel='msedge',headless=True);page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.route('**/*',lambda r:r.continue_() if r.request.url.startswith('http://127.0.0.1:') else r.abort())
                    page.goto(f'http://127.0.0.1:{server.server_port}/');page.wait_for_function("location.hash==='#market'")
                    self.assertEqual(page.locator('#page-tabs [data-page]').all_text_contents(),['市场','投研','账户'])
                    self.assertFalse(page.locator('#account-page').is_visible())
                    page.locator('[data-page="research"]').click();page.locator('[data-research-view="news"]').click();page.wait_for_selector('#news-list .news-item');page.locator('[data-research-view="analysis"]').click();page.locator('#research-list button').first.click();page.wait_for_selector('#huatai-docs h3')
                    self.assertTrue(page.locator('#huatai-panel').is_visible())
                    self.assertEqual(page.locator('#market-page #news-panel').count(),0)
                    for width in (390,768,1240,1920):
                        page.set_viewport_size({'width':width,'height':950})
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
                    page.reload();page.wait_for_function("DashboardNavigation.active==='research'")
                    page.locator('[data-page="account"]').click();page.wait_for_selector('#import-open')
                    self.assertTrue(page.locator('#total').is_visible());self.assertFalse(errors,errors)
                    browser.close()
                self.assertEqual(path.read_bytes(),before)
            finally:server.shutdown();server.server_close();t.join()


if __name__=='__main__':unittest.main()
