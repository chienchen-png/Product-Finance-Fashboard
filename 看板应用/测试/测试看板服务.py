import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码'))
"""临时账户与模拟报价验收，不调用金融接口，不更改正式台账。"""
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from urllib.parse import quote

import 账户核心 as core
import 账户台账 as ledger
import 路径
from 看板服务 import create_server, Updater, LEASE, in_session, pick_port, run_sync


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.calls = [0], []
        self.updater = Updater(Path('unused'), runner=lambda _: self.calls.append(1) or {},
                               clock=lambda: self.clock[0], session=lambda: True)

    def test_interval_stop_manual_and_single_job(self):
        self.updater.command('start', 'tab', 5)
        self.assertTrue(self.updater.tick())
        self.clock[0] = 299
        self.updater.state('tab')
        self.assertFalse(self.updater.tick())
        self.clock[0] = 300
        self.assertTrue(self.updater.tick())
        self.updater.command('start', 'tab', 20)
        self.assertFalse(self.updater.tick())
        self.clock[0] = 1500
        self.updater.state('tab')
        self.assertTrue(self.updater.tick())
        self.updater.command('stop', 'tab')
        self.assertFalse(self.updater.tick())
        self.updater.command('refresh', 'tab')
        self.assertTrue(self.updater.tick())
        self.assertFalse(self.updater.enabled)
        self.updater.busy = True
        self.updater.command('refresh', 'tab')
        self.assertFalse(self.updater.tick())
        self.assertEqual(len(self.calls), 4)

    def test_real_sync_runner_respects_selected_twenty_minutes(self):
        from unittest.mock import patch
        self.updater.runner=run_sync
        self.updater.idle_exit=0
        with patch('看板服务.market.sync',return_value={}):
            self.updater.command('start','tab',20)
            self.assertTrue(self.updater.tick())
            self.assertEqual(self.updater.due,1200)
            self.clock[0]=60;self.updater.state('tab')
            self.assertFalse(self.updater.tick())
            self.clock[0]=1200;self.updater.state('tab')
            self.assertTrue(self.updater.tick())

    def test_closed_tab_expires_and_non_session_waits(self):
        self.updater.command('start', 'tab')
        self.clock[0] = LEASE+1
        self.assertFalse(self.updater.tick())
        self.assertFalse(self.updater.enabled)
        self.updater.session = lambda: False
        self.updater.command('start', 'tab')
        self.assertTrue(self.updater.tick())
        self.clock[0] += 301
        self.updater.state('tab')
        self.assertFalse(self.updater.tick())
        self.assertTrue(self.updater.state()['waiting'])

    def test_startup_sync_runs_once_without_page_client(self):
        self.updater.session = lambda: False
        self.updater.initial = True
        self.assertTrue(self.updater.tick())
        self.assertFalse(self.updater.tick())
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.updater.enabled)

    def test_auth_stops_and_network_failure_keeps_old_data(self):
        self.updater.runner = lambda _: {'报价失败': [{'category': 'auth'}]}
        self.updater.command('start', 'tab')
        self.updater.tick()
        self.assertFalse(self.updater.enabled)
        self.updater.runner = lambda _: {'K线失败': [{'原因': '网络'}]}
        self.updater.command('start', 'tab')
        self.updater.tick()
        self.assertTrue(self.updater.enabled)
        self.assertTrue(self.updater.error)

    def test_idle_exit_fires_once_after_clients_silent(self):
        events = []
        self.updater.on_idle = lambda: events.append(1)
        self.updater.command('start', 'tab')
        self.updater.state('tab')
        self.updater.tick()
        self.clock[0] = 100
        self.assertEqual(self.updater.idle_seconds(), 100)
        self.updater.tick()
        self.assertEqual(events, [])
        self.clock[0] = 300
        self.updater.tick()
        self.assertEqual(events, [1])
        self.updater.tick()
        self.assertEqual(events, [1])

    def test_idle_exit_without_any_client_uses_startup_grace(self):
        events = []
        self.updater.on_idle = lambda: events.append(1)
        self.clock[0] = 599
        self.updater.tick()
        self.assertEqual(events, [])
        self.clock[0] = 600
        self.updater.tick()
        self.assertEqual(events, [1])

    def test_session_uses_beijing_weekday_and_trading_windows(self):
        from datetime import datetime
        self.assertTrue(in_session(datetime.fromisoformat('2026-10-14T10:00:00+08:00')))
        self.assertFalse(in_session(datetime.fromisoformat('2026-10-14T12:00:00+08:00')))
        self.assertFalse(in_session(datetime.fromisoformat('2026-10-17T10:00:00+08:00')))
        self.assertFalse(in_session(datetime.fromisoformat('2026-10-06T10:00:00+08:00')))
        self.assertFalse(in_session(datetime.fromisoformat('2026-10-10T10:00:00+08:00')))
        self.assertTrue(in_session(datetime.fromisoformat('2026-10-14T09:15:00+08:00')))
        self.assertTrue(in_session(datetime.fromisoformat('2026-10-14T02:00:00+00:00')))
        self.assertFalse(in_session(datetime.fromisoformat('2027-01-05T10:00:00+08:00')))


class LocalServerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / '账户.json'
        self.real = ledger.DEFAULT
        self.real_hash = hashlib.sha256(self.real.read_bytes()).hexdigest() if self.real.exists() else None
        # 通用测试使用合成账户，不依赖或复制作者个人台账。
        ledger.init(self.path)
        ledger.record(self.path,dict(id='fixture',time=core.now(),code='510300',exchange='SH',
            name='测试ETF',side='buy',quantity=1000,price='4',fee='1.20',
            confirmation=dict(quantity='confirmed',price='confirmed',fee='confirmed',time='confirmed')))
        cache=core.load_cache(self.path)
        cache['quotes']={'SH:510300':dict(price='4',requested_at=core.now(),source_as_of=core.now())}
        cache['series']={'SH:510300':{'name':'测试ETF','day':dict(
            bars=[['2026-10-15','4','4','4.1','3.9','1000','4000']],
            columns=['time','open','close','high','low','volume','amount'],
            updated_at=core.now(),source='test',adjustment='raw',volume_unit='shares',amount_unit='CNY')}}
        core.save_cache(self.path,cache)
        ledger.render(self.path)
        self.calls = 0

        def fake_sync(path):
            self.calls += 1
            cache = core.load_cache(path)
            for quote in cache.get('quotes', {}).values():
                quote['price'] = str(Decimal(quote['price']) + Decimal('.01'))
                quote['requested_at'] = core.now()
            core.save_cache(path, cache)
            core.append_observation(path, '测试行情估值')
            return {'报价失败': [], 'K线失败': []}

        self.server = create_server(self.path, port=0, runner=fake_sync)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        body = urllib.request.urlopen(self.url).read().decode('utf-8')
        self.token = body.split("localToken='")[1].split("'")[0]

    def tearDown(self):
        self.server.updater.shutdown.set()
        self.server.shutdown()
        self.server.server_close()
        self.folder.cleanup()
        if self.real_hash is None:
            self.assertFalse(self.real.exists())
        else:
            self.assertEqual(hashlib.sha256(self.real.read_bytes()).hexdigest(), self.real_hash)

    def request(self, route, body=None, headers=None):
        headers = dict(headers or {})
        if body is not None:
            headers.setdefault('Content-Type', 'application/json')
        request = urllib.request.Request(self.url+quote(route, safe='/?=&'), data=json.dumps(body).encode() if body else None,
                                         headers=headers)
        try:
            with urllib.request.urlopen(request) as result:
                return result.status, result.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read()

    def test_restricted_routes_tokens_and_origins(self):
        body = {'action': 'start', 'client': 'tab', 'interval': 5}
        headers = {'X-Dashboard-Token': self.token, 'Origin': self.url}
        self.assertEqual(self.request('/api/control', body)[0], 403)
        self.assertEqual(self.request('/api/control', body, dict(headers, Origin='https://example.com'))[0], 403)
        self.assertEqual(self.request('/api/control', dict(body, action='submitOrder'), headers)[0], 400)
        self.assertEqual(self.request('/api/control', dict(body, interval=0), headers)[0], 400)
        self.assertEqual(self.request('/api/control', body, headers)[0], 200)
        # 未带令牌时本地文件路径既不泄露内容也不透露路由是否存在。
        for route in ('/账户.json', '/../AGENTS.md', '/行情缓存.json'):
            status, content = self.request(route)
            self.assertEqual(status, 403)
            self.assertNotIn(b'initial_cash', content)
            self.assertEqual(self.request(route, headers=headers)[0], 404)
        self.assertEqual(self.request('/api/state?client=tab', headers=headers)[0], 200)

    def test_host_header_accepts_localhost_and_rejects_foreign(self):
        port = self.server.server_port
        self.assertEqual(self.request('/', headers={'Host': f'127.0.0.1:{port}'})[0], 200)
        self.assertEqual(self.request('/', headers={'Host': f'localhost:{port}'})[0], 200)
        self.assertEqual(self.request('/', headers={'Host': f'evil.example:{port}'})[0], 403)

    def test_health_and_state_expose_identity_and_port(self):
        status, content = self.request('/health')
        health = json.loads(content)
        self.assertEqual(status, 200)
        self.assertEqual(health['app'], 'competition-dashboard-v3.0.1')
        self.assertEqual(health['pid'], os.getpid())
        self.assertEqual(health['data_root'], str(路径.数据根()))
        self.assertTrue(health['started_at'])
        state = json.loads(self.request('/api/state?client=tab',
                                        headers={'X-Dashboard-Token': self.token})[1])
        self.assertEqual(state['port'], self.server.server_port)


    def test_sync_runs_in_process_and_passes_report_through(self):
        from unittest.mock import patch
        report = {'报价失败': [{'category': 'auth'}], 'K线失败': []}
        with patch('看板服务.market.sync', return_value=report) as fake:
            self.assertEqual(run_sync(self.path), report)
        fake.assert_called_once_with(self.path)

    def test_browser_start_update_restore_and_stop(self):
        from playwright.sync_api import sync_playwright
        worker = threading.Thread(target=self.server.updater.loop, daemon=True)
        worker.start()
        with sync_playwright() as engine:
            browser = engine.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1100})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(self.url)
            page.wait_for_function("document.getElementById('live-state').textContent==='已停止'")
            page.locator('#live-interval').select_option('20')
            page.locator('#positions .pos').first.click()
            page.wait_for_selector('.kbtn[data-t="g"][data-v="day"]')
            page.locator('.kbtn[data-t="g"][data-v="day"]').first.click()
            page.wait_for_selector('.kbtn[data-t="range"][data-v="all"]')
            page.locator('.kbtn[data-t="range"][data-v="all"]').first.click()
            initial = page.locator('#market').inner_text()
            page.locator('#live-toggle').click()
            page.wait_for_function("document.getElementById('live-toggle').textContent==='停止联动'")
            page.wait_for_function('(value)=>document.getElementById("market").textContent!==value', arg=initial, timeout=20000)
            self.assertTrue(page.locator('#positions .pos').first.get_attribute('aria-expanded') == 'true')
            self.assertIn('on', page.locator('.kbtn[data-v="day"]').first.get_attribute('class'))
            self.assertIn('on', page.locator('.kbtn[data-v="all"]').first.get_attribute('class'))
            self.assertEqual(page.locator('#live-interval').input_value(), '20')
            self.assertEqual(self.calls, 1)
            page.locator('#live-toggle').click()
            page.wait_for_function("document.getElementById('live-toggle').textContent==='启动联动'")
            initial = page.locator('#market').inner_text()
            page.locator('#refresh-button').click()
            page.wait_for_function('(value)=>document.getElementById("market").textContent!==value', arg=initial, timeout=20000)
            self.assertEqual(self.calls, 2)
            self.assertFalse(self.server.updater.enabled)
            self.assertFalse(errors, errors)
            browser.close()

    def test_browser_unknown_money_displays_pending_not_zero(self):
        account = core.load_account(self.path)
        account.pop('reconciliations', None)  # 该场景没有用户确认的现金基线。
        account['trades'] = [{'id':'unknown','time':None,'trade_date':core.now()[:10],
            'code':'512890','exchange':'SH','name':'测试ETF','side':'buy',
            'quantity':100,'price':'1.212','fee':None}]
        core.save_account(self.path, account)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as engine:
            browser = engine.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(self.url)
            page.wait_for_function("document.getElementById('cash').textContent !== '—'")
            self.assertIn('待核', page.locator('#cash').inner_text())
            self.assertNotIn('¥0.00', page.locator('#cash').inner_text())
            self.assertFalse(errors)
            browser.close()

    def test_browser_confirmed_report_displays_known_cash_and_profit(self):
        core.save_cache(self.path,core.empty_cache())
        account = core.load_account(self.path)
        account.update(trades=[],pending_orders=[],reconciliations=[])
        core.save_account(self.path,account)
        ledger.record(self.path,dict(id='phone-buy',time=None,trade_date=core.now()[:10],code='510300',exchange='SH',
            name='测试ETF',side='buy',quantity=100,price=None,fee=None,confirmation={'quantity':'confirmed'}))
        ledger.reconcile(self.path,{'id':'phone-test','summary':{'total_assets':'1000000','market_value':'1000',
            'available_cash':'999000','daily_profit':'-5','unrealized_profit':'-10'},
            'positions':[dict(key='SH:510300',code='510300',exchange='SH',name='测试ETF',quantity=100,average_cost='10.1',price='10')]})
        from playwright.sync_api import sync_playwright
        with sync_playwright() as engine:
            browser=engine.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page();page.goto(self.url)
            page.wait_for_function("document.getElementById('cash').textContent!=='—'")
            self.assertEqual(page.locator('#cash').inner_text(),'¥999,000.00')
            self.assertEqual(page.locator('#total').inner_text(),'¥1,000,000.00')
            self.assertIn('-5.00',page.locator('#daily-profit').inner_text())
            self.assertIn('-10.00',page.locator('#count').inner_text())
            self.assertIn('10.1000',page.locator('#positions .pos').first.inner_text())
            browser.close()


class PortTests(unittest.TestCase):
    def test_free_port_is_returned_without_http_probe(self):
        def probe(port):
            raise AssertionError('空闲端口不应触发HTTP探测')
        self.assertEqual(pick_port(Path('D:/数据'), ports=range(8765, 8776), probe_fn=probe,
                                   free_fn=lambda port: True), ('start', 8765))

    def test_pick_port_reuses_matching_instance(self):
        def probe(port):
            return {'app': 'competition-dashboard-v3.0.1', 'data_root': str(Path('D:/数据'))}
        self.assertEqual(pick_port(Path('D:/数据'), ports=range(8765, 8768), probe_fn=probe,
                                   free_fn=lambda port: False), ('reuse', 8765))

    def test_pick_port_scans_all_ports_before_binding_free_one(self):
        def probe(port):
            if port == 8765:
                return {'app': 'other'}
            return {'app': 'competition-dashboard-v3.0.1', 'data_root': str(Path('D:/别的'))}
        self.assertEqual(pick_port(Path('D:/数据'), ports=range(8765, 8768), probe_fn=probe,
                                   free_fn=lambda port: port == 8767), ('start', 8767))

    def test_pick_port_raises_when_all_taken(self):
        with self.assertRaises(ValueError):
            pick_port(Path('D:/数据'), ports=range(8765, 8767), probe_fn=lambda port: {'app': 'other'},
                      free_fn=lambda port: False)


if __name__ == '__main__':
    unittest.main()
