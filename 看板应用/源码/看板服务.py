#!/usr/bin/env python3
"""仅本机的看板服务：公开行情、事实录入；不提供券商交易或任意文件接口。"""
import argparse
from datetime import datetime, time as daytime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit
import urllib.request
import webbrowser

import 账户核心 as core
import 行情同步 as market
import 路径
import 市场同步 as shared_market
from 数据契约 import validate_symbol
from 指标 import chart_series
import 账户录入 as entry_import

ROOT, DEFAULT = core.ROOT, core.DEFAULT
TZ = timezone(timedelta(hours=8))
APP = 'competition-dashboard-v3.0.1'
LEASE = 180
IDLE_EXIT_SECONDS = 300
STARTUP_IDLE_EXIT_SECONDS = 600
CALENDAR = core.read_json(路径.资源路径('看板应用/资源/A股交易日历.json'))
lookup_cache = {}  # 录入表单名称查询的短缓存：symbol -> (monotonic, quote)


def is_trading_day(value):
    stamp = value.isoformat()
    if not CALENDAR['valid_from'] <= stamp <= CALENDAR['valid_to']:
        return None
    return value.weekday() < 5 and not any(item['from'] <= stamp <= item['to'] for item in CALENDAR['holidays'])


def in_session(value=None):
    value = value or datetime.now(TZ)
    if value.tzinfo:
        value = value.astimezone(TZ)
    clock = value.time().replace(tzinfo=None)
    return is_trading_day(value.date()) is True and any(
        daytime.fromisoformat(start) <= clock <= daytime.fromisoformat(end)
        for start, end in CALENDAR['poll_windows'])


def run_sync(path):
    return market.sync(path)


def probe(port, timeout=1):
    """读另一实例的/health：无监听返回None，非本服务返回其响应。"""
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=timeout) as response:
            raw = response.read()
    except OSError:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return {'app': None}


def port_free(port):
    """试绑判断端口空闲；不设SO_REUSEADDR，Windows占用端口会立即报错。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(('127.0.0.1', port))
        except OSError:
            return False
    return True


def pick_port(data_root, ports=None, probe_fn=None, free_fn=None):
    """空闲端口直接返回；只有被占端口才发HTTP探测，避免冷启动逐个超时。"""
    root = str(Path(data_root))
    probe_fn = probe_fn or probe
    free_fn = free_fn or port_free
    ports = list(ports if ports is not None else range(8765, 8776))
    states = [(port, None if free_fn(port) else probe_fn(port)) for port in ports]
    for port, state in states:
        if state and state.get('app') == APP and str(state.get('data_root') or state.get('workspace')) == root:
            return 'reuse', port
    for port, state in states:
        if state is None:
            return 'start', port
    raise ValueError(f'{ports[0]}-{ports[-1]}端口均被占用，关闭其他程序后重试')


class Updater:
    def __init__(self, path, runner=run_sync, clock=time.monotonic, session=in_session,
                 idle_exit=IDLE_EXIT_SECONDS, startup_idle_exit=STARTUP_IDLE_EXIT_SECONDS, on_idle=None):
        self.path, self.runner, self.clock, self.session = Path(path), runner, clock, session
        self.lock = threading.RLock()
        self.enabled, self.busy, self.force, self.initial = False, False, False, False
        self.interval, self.due = 5, 0
        self.clients, self.error, self.last_completed = {}, '', None
        self.idle_exit, self.startup_idle_exit, self.on_idle = idle_exit, startup_idle_exit, on_idle
        self.started, self.last_client_seen, self.seen_any, self.exited = self.clock(), None, False, False
        self.shutdown = threading.Event()

    def _heartbeat(self, client):
        stamp = self.clock()
        self.clients[client] = stamp
        self.seen_any, self.last_client_seen = True, stamp

    def idle_seconds(self):
        """距最近一次客户端心跳（从未有过客户端则为距启动）的秒数。"""
        with self.lock:
            return self.clock() - (self.last_client_seen if self.seen_any else self.started)

    def command(self, action, client, interval=5):
        if not re.fullmatch(r'[A-Za-z0-9-]{1,64}', client or ''):
            raise ValueError('无效页面标识')
        if action not in ('start', 'stop', 'refresh') or interval not in (5, 20):
            raise ValueError('无效更新参数')
        with self.lock:
            self._heartbeat(client)
            if action == 'start':
                was_enabled = self.enabled
                self.enabled, self.interval = True, interval
                if not was_enabled and not self.busy:
                    self.force = True
                self.due = self.clock() + interval * 60
            elif action == 'stop':
                self.enabled, self.force = False, False
            elif not self.busy:
                self.force = True

    def _expire(self):
        self.clients = {key: stamp for key, stamp in self.clients.items() if self.clock() - stamp < LEASE}
        if not self.clients:
            self.enabled, self.force = False, False

    def state(self, client=None):
        with self.lock:
            if client and re.fullmatch(r'[A-Za-z0-9-]{1,64}', client):
                self._heartbeat(client)
            self._expire()
            return {'running': self.enabled, 'busy': self.busy, 'interval': self.interval,
                    'waiting': self.enabled and not self.session(), 'error': self.error,
                    'last_completed': self.last_completed}

    def tick(self):
        if self.path.is_file():
            core.observe_account(self.path)
            if self.runner is run_sync and shared_market.collector(self.path)._requests:
                self.initial = True
        exit_now = False
        with self.lock:
            self._expire()
            limit = self.idle_exit if self.seen_any else self.startup_idle_exit
            if limit > 0 and not self.exited and self.idle_seconds() >= limit:
                self.exited, exit_now = True, True
            due = self.initial or self.force or (self.enabled and (self.session() or self.runner is run_sync) and self.clock() >= self.due)
            if exit_now or self.busy or not due:
                run = False
            else:
                self.busy, self.initial, self.force, self.error = True, False, False, ''
                run = True
        if exit_now:
            if self.on_idle:
                self.on_idle()
            return False
        if not run:
            return False
        try:
            report = self.runner(self.path)
            failures = list(report.get('报价失败', [])) + list(report.get('K线失败', []))
            categories = {item.get('category') for item in report.get('报价失败', [])}
            with self.lock:
                self.last_completed = core.now()
                self.error = f'{len(failures)}项未更新，沿用旧值' if failures else ''
                if 'auth' in categories:
                    self.enabled = False
        except Exception:
            with self.lock:
                self.error = '更新失败，已保留原数据'
        finally:
            with self.lock:
                self.busy = False
                self.due = self.clock() + self.interval * 60
        return True

    def loop(self):
        while not self.shutdown.wait(1):
            try:
                self.tick()
            except (ValueError, OSError):
                # AI/网页正在提交事实时下轮重读；后台线程不能因短锁冲突退出。
                with self.lock:
                    self.error = '账户更新中，稍后重试'


def create_server(path=DEFAULT, port=8765, runner=run_sync):
    path = Path(path)
    raw = core.read_json(path)
    if raw.get('version') != 2:
        core.migrate(path)
    core.load_account(path)
    token = secrets.token_urlsafe(24)
    started_at = core.now()
    template = 路径.资源路径('看板应用/源码/账户看板模板.html').read_text(encoding='utf-8')
    chart_file = 路径.资源路径('看板应用/源码/图表依赖/echarts.min.js')
    chart_bytes = chart_file.read_bytes()
    chart_etag = '"' + hashlib.sha256(chart_bytes).hexdigest() + '"'
    updater = Updater(path, runner=runner)
    previews = {}
    preview_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = 'CompetitionDashboard/2'

        def log_message(self, *_):
            return

        def allowed_host(self):
            port = self.server.server_port
            return self.headers.get('Host', '') in (f'127.0.0.1:{port}', f'localhost:{port}')

        def authorized(self):
            origin = self.headers.get('Origin')
            expected = f'http://127.0.0.1:{self.server.server_port}'
            return self.allowed_host() and (not origin or origin == expected) and \
                secrets.compare_digest(self.headers.get('X-Dashboard-Token', ''), token)

        def revision(self):
            parts = []
            for target in (path, core.cache_path(path), core.nav_path(path)):
                try:
                    stat = target.stat()
                    parts.append(f'{stat.st_mtime_ns}:{stat.st_size}')
                except OSError:
                    parts.append('missing')
            parts.append(str(int(time.time()) // 60))
            return hashlib.sha256('|'.join(parts).encode()).hexdigest()[:16]

        def send_bytes(self, body, content_type, status=200, cache='no-store', etag=None):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', cache)
            self.send_header('X-Content-Type-Options', 'nosniff')
            if etag:
                self.send_header('ETag', etag)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            if self.command != 'HEAD':
                try:
                    self.wfile.write(body)
                except ConnectionError:
                    # 切页/关页取消请求属于正常断连，不记为接口或账务异常。
                    pass

        def send_json(self, data, status=200, etag=None):
            if etag and self.headers.get('If-None-Match') == etag:
                return self.send_bytes(b'', 'application/json; charset=utf-8', 304, 'no-cache', etag)
            body = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            self.send_bytes(body, 'application/json; charset=utf-8', status, 'no-cache', etag)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            parsed = urlsplit(self.path)
            route = parsed.path
            if not self.allowed_host():
                return self.send_json({'error': 'forbidden'}, 403)
            if route == '/health':
                return self.send_json({'app': APP, 'version': 3, 'pid': os.getpid(),
                                       'data_root': str(路径.数据根()), 'workspace': str(路径.数据根()),
                                       'started_at': started_at})
            if route == '/':
                html = template.replace('__ACCOUNT_DATA__', 'null') \
                    .replace('__CHART_TAG__', '<script src="/assets/echarts.min.js"></script>') \
                    .replace('__CHART_LIBRARY__', '').replace('__LOCAL_TOKEN__', token) \
                    .replace('__LIVE_REVISION__', self.revision())
                html = html.replace('__EXTRA_SCRIPTS__','<script src="/assets/market.js"></script><script src="/assets/entry.js"></script>')
                return self.send_bytes(html.encode('utf-8'), 'text/html; charset=utf-8')
            if route in ('/assets/market.js','/assets/entry.js'):
                name = '市场看板.js' if route.endswith('market.js') else '账户录入.js'
                body = 路径.资源路径('看板应用/源码/'+name).read_bytes()
                return self.send_bytes(body,'text/javascript; charset=utf-8',cache='no-cache')
            if route == '/assets/echarts.min.js':
                if self.headers.get('If-None-Match') == chart_etag:
                    return self.send_bytes(b'', 'text/javascript; charset=utf-8', 304,
                                           'public,max-age=31536000,immutable', chart_etag)
                return self.send_bytes(chart_bytes, 'text/javascript; charset=utf-8', cache='public,max-age=31536000,immutable', etag=chart_etag)
            if route == '/favicon.ico':
                return self.send_bytes(b'', 'image/x-icon', 204)
            if not self.authorized():
                return self.send_json({'error': 'forbidden'}, 403)
            revision = self.revision()
            if route == '/api/view':
                return self.send_json(core.view_model(path), etag='"view-' + revision + '"')
            if route == '/api/market':
                query = parse_qs(parsed.query)
                section = (query.get('section') or ['overview'])[0]
                if section not in shared_market.SECTIONS:
                    return self.send_json({'error':'invalid_section'},400)
                key = section
                if section in ('flows','announcements'):
                    return self.send_json({'error':'capability_not_enabled'},400)
                if section == 'ranks':
                    product = (query.get('product_type') or ['stock'])[0]
                    sort = (query.get('sort') or ['up'])[0]
                    if product not in ('stock','etf','lof') or sort not in ('up','down','amount','turnover'):
                        return self.send_json({'error':'invalid_rank'},400)
                    key += ':' + product + ':' + sort
                elif section == 'sectors':
                    group = (query.get('group') or ['industry'])[0]
                    if group not in shared_market.capabilities()['sectors']:
                        return self.send_json({'error':'invalid_group'},400)
                    key += ':' + group
                elif section in ('nav','announcements'):
                    symbol = (query.get('symbol') or [''])[0]
                    try: validate_symbol(symbol)
                    except ValueError:return self.send_json({'error':'invalid_symbol'},400)
                    key += ':' + symbol
                value = shared_market.read_section(path,key)
                if section in ('overview','ranks'):
                    shared_market.collector(path).prefetch([r['symbol'] for r in value.get('data',[]) if r.get('symbol')])
                return self.send_json(value,etag='"market-'+value['revision']+'"')
            if route == '/api/instruments':
                q = (parse_qs(parsed.query).get('q') or [''])[0][:50].casefold()
                rows = shared_market.tracked_products(path)
                return self.send_json({'data':[r for r in rows if q in r['symbol'].casefold() or q in r.get('name','').casefold()][:20]})
            if route == '/api/lookup':
                # 录入表单用：按代码取名称与最新价。只读公开行情，30秒内复用，最多缓存200项。
                symbol = (parse_qs(parsed.query).get('symbol') or [''])[0]
                try:
                    validate_symbol(symbol)
                except ValueError:
                    return self.send_json({'error': 'invalid_symbol'}, 400)
                now = time.monotonic()
                hit = lookup_cache.get(symbol)
                if not hit or now - hit[0] > 30:
                    from 数据源.公共行情 import fetch_quotes as fetch_public
                    try:
                        hit = (now, fetch_public([symbol]).get(symbol))
                    except (OSError, ValueError, KeyError, TypeError, ArithmeticError):
                        hit = (now, None)
                    lookup_cache[symbol] = hit
                    if len(lookup_cache) > 200:
                        for key in sorted(lookup_cache, key=lambda k: lookup_cache[k][0])[:100]:
                            lookup_cache.pop(key, None)
                quote = hit[1]
                if not quote:
                    return self.send_json({'symbol': symbol, 'found': False}, 404)
                return self.send_json({'symbol': symbol, 'found': True, 'name': quote.get('name'),
                                       'price': quote.get('price'), 'prev_close': quote.get('prev_close'),
                                       'change_pct': quote.get('change_pct'), 'source_as_of': quote.get('source_as_of')})
            if route == '/api/kline':
                query = parse_qs(parsed.query)
                symbol = (query.get('symbol') or [''])[0]
                period = (query.get('period') or ['day'])[0]
                adjustment = (query.get('adjustment') or ['raw'])[0]
                try: validate_symbol(symbol)
                except ValueError:
                    return self.send_json({'error': 'invalid_symbol'}, 400)
                if period not in ('day','m5') or adjustment not in ('raw','qfq'):
                    return self.send_json({'error':'invalid_period'},400)
                entry = core.load_cache(path).get('series', {}).get(symbol)
                key = period if adjustment=='raw' else period+'_qfq'
                engine = shared_market.collector(path)
                state = engine.kline_state(symbol,period,adjustment,entry)
                if state['status']=='pending':
                    # 排队有界；GET只触发内存任务，不写文件或在HTTP线程取外网。
                    try:
                        engine.queue(f'kline:{symbol}:{period}:{adjustment}')
                        with updater.lock:updater.force=True
                    except ValueError as exc:
                        return self.send_json({'error':str(exc)},429)
                data = chart_series(entry,core.now(),symbol) if entry else None
                return self.send_json(dict(state,symbol=symbol,data=data),
                    etag='"kline-'+revision+'-'+symbol+'-'+period+'-'+adjustment+'"')
            if route == '/api/state':
                client = (parse_qs(parsed.query).get('client') or [None])[0]
                state = updater.state(client)
                state['revision'] = revision
                state['port'] = self.server.server_port
                return self.send_json(state)
            return self.send_json({'error': 'not_found'}, 404)

        def do_POST(self):
            if self.path in ('/api/import/preview','/api/import/commit'):
                if not self.authorized():
                    return self.send_json({'error':'forbidden'},403)
                try:
                    size = int(self.headers.get('Content-Length','0'))
                    if not 2 <= size <= 1024*1024 or self.headers.get_content_type()!='application/json':
                        raise ValueError('导入限1MiB JSON')
                    payload = json.loads(self.rfile.read(size))
                    if not isinstance(payload,dict):raise ValueError('请求必须为对象')
                    with preview_lock:
                        for key in list(previews):
                            if previews[key]['expires']<time.monotonic():del previews[key]
                        if self.path.endswith('/preview'):
                            account = core.load_account(path)
                            if payload.get('kind')=='watchlist':
                                payload['expected_watchlist_revision']=core.account_revision(core.read_json(
                                    shared_market.watchlist_path(path),{'schema_version':1,'products':[]}))
                            result = entry_import.preview_import(account,payload)
                            if result['errors']:return self.send_json(result,400)
                            if len(previews)>=20:raise ValueError('预览过多，请稍后重试')
                            nonce = secrets.token_urlsafe(24)
                            previews[nonce] = dict(payload=payload,revision=result['revision'],expires=time.monotonic()+300,result=None)
                            # 预览仅回显变更与错误，不把整份账户再复制给浏览器。
                            return self.send_json({k:v for k,v in dict(result,token=nonce).items() if k!='normalized'})
                        item = previews.get(payload.get('token',''))
                        if not item:raise ValueError('预览不存在或已过期，请重新预览')
                        if payload.get('expected_revision')!=item['revision']:
                            raise entry_import.RevisionConflict('预览版本不符')
                        if item['result'] is None:
                            item['result']=entry_import.commit_import(path,item['payload'],item['revision'])
                            shared_market.collector(path).queue('overview')
                            with updater.lock:updater.force=True
                        return self.send_json(item['result'])
                except entry_import.RevisionConflict as exc:
                    return self.send_json({'errors':[str(exc)]},409)
                except (ValueError,TypeError,KeyError,OSError,ArithmeticError) as exc:
                    return self.send_json({'errors':[str(exc)]},400)
            if self.path != '/api/control' or not self.authorized():
                return self.send_json({'error': 'forbidden'}, 403)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if size < 2 or size > 2048 or self.headers.get_content_type() != 'application/json':
                    raise ValueError('invalid_body')
                payload = json.loads(self.rfile.read(size))
                updater.command(payload.get('action'), payload.get('client'), payload.get('interval', 5))
                if payload.get('action')=='refresh':shared_market.collector(path).request_refresh()
                return self.send_json(updater.state(payload.get('client')))
            except (ValueError, TypeError, json.JSONDecodeError):
                return self.send_json({'error': 'invalid_request'}, 400)

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.updater, server.local_token = updater, token
    lookup_cache.clear()
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, default=DEFAULT)
    parser.add_argument('--port', type=int, default=None, help='起始端口；默认从8765顺延，遇同数据根实例直接复用')
    parser.add_argument('--open', action='store_true')
    parser.add_argument('--idle-exit', type=int, default=IDLE_EXIT_SECONDS, help='全部页面关闭后自动退出秒数，0为不退出')
    parser.add_argument('--startup-idle-exit', type=int, default=STARTUP_IDLE_EXIT_SECONDS, help='从未打开页面时的退出秒数')
    args = parser.parse_args()
    ports = range(args.port, args.port + 1) if args.port else range(8765, 8776)
    action, port = pick_port(路径.数据根(), ports)
    url = f'http://127.0.0.1:{port}/'
    if action == 'reuse':
        if args.open:
            webbrowser.open(url)
        return
    server = create_server(args.file, port)
    server.updater.idle_exit = args.idle_exit
    server.updater.startup_idle_exit = args.startup_idle_exit
    server.updater.on_idle = server.shutdown
    with server.updater.lock:
        # 启动后先同步一次行情；是否继续定时轮询仍由网页上的联动开关决定。
        server.updater.initial = True
    worker = threading.Thread(target=server.updater.loop, daemon=True)
    worker.start()
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        server.updater.shutdown.set()
        server.server_close()


if __name__ == '__main__':
    main()
