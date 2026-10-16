import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码'))
import tempfile
import threading
import unittest
from unittest.mock import patch
import 账户核心 as core
import 账户台账 as ledger
from 看板服务 import create_server


class EntryBrowserTests(unittest.TestCase):
    def test_teammate_opening_form_buy_sell_duplicate_and_mobile(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as folder,patch('数据源.公共行情.fetch_quotes',side_effect=lambda symbols:{symbol:dict(name='沪深300ETF' if symbol=='SH:510300' else '恒生ETF',price='4',source_as_of=core.now()) for symbol in symbols}):
            path=Path(folder)/'账户记录/比赛账户.json';ledger.init(path)
            server=create_server(path,0,runner=lambda _:{});thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with sync_playwright() as engine:
                    browser=engine.chromium.launch(channel='msedge',headless=True)
                    page=browser.new_page(viewport={'width':1280,'height':900},timezone_id='America/New_York')
                    page.route('**/*',lambda r:r.continue_() if r.request.url.startswith('http://127.0.0.1:') else r.abort())
                    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/')
                    page.wait_for_function("document.getElementById('cash').textContent==='¥1,000,000.00'")
                    self.assertEqual(page.locator('#positions .pos').count(),0)
                    page.locator('#import-open').click()
                    page.locator('#import-kind').select_option('snapshot')
                    self.assertTrue(page.locator('#snapshot-fields').is_visible())
                    self.assertFalse(page.locator('#file-fields').is_visible())
                    for field,value in [('total','1000000'),('cash','999600'),('market','400')]:
                        page.locator(f'[name="snapshot_{field}"]').fill(value)
                    page.locator('#snapshot-add').click()
                    for field,value in [('code','510300'),('quantity','100'),('average_cost','4'),('price','4')]:
                        page.locator(f'#snapshot-rows [data-field="{field}"]').fill(value)
                    page.locator('#import-preview').click()
                    page.wait_for_function("!document.getElementById('import-commit').disabled")
                    self.assertNotIn('reconciliations',ledger.load(path))
                    page.locator('#import-commit').click()
                    page.wait_for_function("document.querySelectorAll('#positions .pos').length===1")
                    self.assertTrue(ledger.load(path)['reconciliations'][0]['opening'])
                    self.assertNotIn('显示均价与账户总成本相差',page.locator('body').inner_text())
                    page.set_viewport_size({'width':390,'height':844})
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390)
                    page.set_viewport_size({'width':1280,'height':900})
                    page.locator('#import-kind').select_option('trades')
                    for field,value in [('code','510300'),('quantity','100'),('trade_price','4'),('trade_time',core.now()[:19])]:
                        page.locator(f'[name="{field}"]').fill(value)
                    for repetition in range(2):
                        page.locator('#import-preview').click()
                        page.wait_for_function("!document.getElementById('import-commit').disabled")
                        page.locator('#import-commit').click()
                        page.wait_for_function("document.getElementById('import-message').textContent.startsWith('已保存')")
                        self.assertEqual(len(ledger.load(path)['trades']),1)
                    self.assertEqual(ledger.load_state(path)['summary']['cash'],'999199.88')
                    page.locator('[name="side"]').select_option('sell')
                    page.locator('#import-preview').click()
                    page.wait_for_function("!document.getElementById('import-commit').disabled")
                    page.locator('#import-commit').click()
                    page.wait_for_function("document.getElementById('cash').textContent==='¥999,599.76'")
                    self.assertEqual(ledger.load_state(path)['summary']['positions'][0]['quantity'],100)
                    page.locator('[name="code"]').fill('159920')
                    page.locator('[name="quantity"]').click()
                    page.wait_for_function("document.querySelector('[name=name]').value==='恒生ETF'")
                    self.assertEqual(page.locator('[name="exchange"]').input_value(),'SZ')
                    self.assertFalse(errors,errors);browser.close()
            finally:server.shutdown();server.server_close();thread.join()

    def test_manual_confirm_updates_account_without_reload(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'账户记录/比赛账户.json';ledger.init(path)
            server=create_server(path,0,runner=lambda _:{});thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with sync_playwright() as engine:
                    browser=engine.chromium.launch(channel='msedge',headless=True)
                    page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/')
                    page.wait_for_function("document.getElementById('cash').textContent!=='—'")
                    page.locator('#import-open').click()
                    page.locator('[name="trade_id"]').fill('phone-1')
                    page.locator('[name="code"]').fill('510300')
                    page.locator('[name="quantity"]').fill('100')
                    page.locator('[name="trade_price"]').fill('4.242')
                    page.locator('[name="fee"]').fill('0')
                    page.locator('#import-preview').click()
                    page.wait_for_function("!document.getElementById('import-commit').disabled")
                    self.assertEqual(ledger.load(path)['trades'],[])
                    page.locator('#import-commit').click()
                    page.wait_for_function("document.getElementById('cash').textContent==='¥999,575.80'")
                    self.assertEqual(len(ledger.load(path)['trades']),1)
                    self.assertFalse(errors,errors);browser.close()
            finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
