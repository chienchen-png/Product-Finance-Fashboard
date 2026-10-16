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
                    page.locator('[data-page=account]').click()
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

    def test_minimal_four_field_entry_and_pending_add(self):
        """网页最小四项录入：方向、代码、数量、成交价；其余字段折叠且非必填。"""
        from playwright.sync_api import sync_playwright
        def 模拟报价(symbols):
            return {symbol:dict(name={'FX:HKDCNY':'港元/人民币','SH:510300':'沪深300ETF'}.get(symbol,'腾讯控股'),
                price='0.852' if symbol=='FX:HKDCNY' else '4.242',source_as_of=core.now()) for symbol in symbols}
        with tempfile.TemporaryDirectory() as folder,patch('数据源.公共行情.fetch_quotes',side_effect=模拟报价):
            path=Path(folder)/'账户记录/比赛账户.json';ledger.init(path)
            server=create_server(path,0,runner=lambda _:{});thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with sync_playwright() as engine:
                    browser=engine.chromium.launch(channel='msedge',headless=True)
                    page=browser.new_page(viewport={'width':1280,'height':900})
                    page.route('**/*',lambda r:r.continue_() if r.request.url.startswith('http://127.0.0.1:') else r.abort())
                    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/')
                    page.locator('[data-page=account]').click()
                    page.wait_for_function("document.getElementById('cash').textContent==='¥1,000,000.00'")
                    page.locator('#import-open').click()
                    self.assertTrue(page.locator('#trade-fields').is_visible())
                    self.assertFalse(page.locator('#pending-fields').is_visible())
                    self.assertFalse(page.locator('#file-fields').is_visible())
                    # 更多信息折叠：名称、交易所、费用、编号不占版面。
                    self.assertIsNone(page.locator('#trade-fields details').get_attribute('open'))
                    self.assertEqual(page.evaluate("[...document.querySelectorAll('#trade-fields [required]')].map(e=>e.name||e.id)"),
                                     ['code','quantity','trade_price'])
                    self.assertNotEqual(page.locator('[name="trade_time"]').input_value(),'')
                    page.locator('[name="code"]').fill('510300')
                    page.locator('[name="quantity"]').fill('100')
                    page.locator('[name="trade_price"]').fill('4.242')
                    page.wait_for_function("document.querySelector('[name=name]').value==='沪深300ETF'")
                    self.assertEqual(page.locator('[name="exchange"]').input_value(),'SH')
                    page.wait_for_function("document.getElementById('trade-hint').textContent.includes('费用约 0.13')")
                    page.locator('#import-preview').click()
                    page.wait_for_function("document.getElementById('import-message').textContent.includes('费用 0.13')")
                    self.assertEqual(ledger.load(path)['trades'],[])
                    page.locator('#import-commit').click()
                    page.wait_for_function("document.getElementById('cash').textContent==='¥999,575.67'")
                    trade=ledger.load(path)['trades'][0]
                    self.assertEqual((trade['exchange'],trade['fee'],trade['confirmation']['fee']),('SH','0.13','rule'))
                    self.assertTrue(trade['id'].startswith('自动-'))
                    # 港股通：5位代码自动定HK，折算率自动带出，看板标注港币。
                    page.locator('[name="code"]').fill('00700')
                    page.locator('[name="quantity"]').fill('100')
                    page.locator('[name="trade_price"]').fill('417.8')
                    page.wait_for_function("document.querySelector('[name=hk_fx]').value==='0.852'")
                    self.assertEqual(page.locator('[name="exchange"]').input_value(),'HK')
                    page.wait_for_function("document.getElementById('trade-hint').textContent.includes('港股通0.1257%')")
                    page.locator('#import-preview').click()
                    page.wait_for_function("document.getElementById('import-message').textContent.includes('费用 52.52')")
                    page.locator('#import-commit').click()
                    page.wait_for_function("document.getElementById('cash').textContent==='¥963,934.36'")
                    hk=[t for t in ledger.load(path)['trades'] if t['exchange']=='HK'][0]
                    self.assertEqual((hk['fx'],hk['amount'],hk['fee']),('0.852','41780.00','52.52'))
                    self.assertIn('港币',page.locator('#positions').inner_text())
                    self.assertIn('港股按',page.locator('#reconcile-note').inner_text())
                    # 委托：同样最小四项，追加而非覆盖，编号与交易所自动生成。
                    page.locator('#import-kind').select_option('pending')
                    self.assertTrue(page.locator('#pending-fields').is_visible())
                    self.assertFalse(page.locator('#trade-fields').is_visible())
                    self.assertEqual(page.evaluate("[...document.querySelectorAll('#trade-fields [required]')].map(e=>e.name)"),[])
                    self.assertEqual(page.evaluate("[...document.querySelectorAll('#pending-fields [required]')].map(e=>e.id)"),
                                     ['pending-code','pending-quantity','pending-price'])
                    page.locator('#pending-code').fill('159920')
                    page.locator('#pending-quantity').fill('40000')
                    page.locator('#pending-price').fill('1.418')
                    page.locator('#import-preview').click()
                    page.wait_for_function("document.getElementById('import-message').textContent.includes('追加委托')")
                    page.locator('#import-commit').click()
                    page.wait_for_function("document.querySelectorAll('#orders tr').length===1&&document.getElementById('orders').textContent.includes('159920')")
                    order=ledger.load(path)['pending_orders'][0]
                    self.assertEqual((order['exchange'],order['amount']),('SZ','56720.00'))
                    self.assertTrue(order['id'].startswith('自动-'))
                    self.assertEqual(len(ledger.load(path)['pending_orders']),1)
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
                    page.locator('[data-page=account]').click()
                    page.wait_for_function("document.getElementById('cash').textContent!=='—'")
                    page.locator('#import-open').click()
                    page.locator('#trade-fields details summary').click()
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
