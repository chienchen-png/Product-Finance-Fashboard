"""本机智能体客户端。Python 3.10+，仅标准库；不连接券商或提交交易。"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


class Client:
    def __init__(self, url):
        parts = urlsplit(url)
        if parts.scheme != 'http' or parts.hostname != '127.0.0.1' or not parts.port or parts.path not in ('', '/') or parts.query or parts.fragment or parts.username:
            raise ValueError('仅接受 http://127.0.0.1:端口')
        self.url = url.rstrip('/')
        health = self.request('/health', authenticated=False)
        if not str(health.get('app', '')).startswith('competition-dashboard-'):
            raise ValueError('目标不是比赛看板服务')
        html = self.request('/', authenticated=False, text=True)
        token = re.search(r"localToken='([^']+)'", html)
        if not token:
            raise ValueError('无法读取本机会话，请重新启动看板')
        self.token = token.group(1)

    def request(self, path, payload=None, authenticated=True, text=False):
        headers = {'X-Dashboard-Token': self.token} if authenticated else {}
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        req = Request(self.url + path, data=data, headers=headers)
        try:
            with urlopen(req, timeout=12) as response:
                body = response.read().decode('utf-8')
                return body if text else json.loads(body)
        except HTTPError as exc:
            try:
                body = json.loads(exc.read().decode('utf-8'))
                reason = '；'.join(body.get('errors', [])) or body.get('error', '请求失败')
            except (ValueError, UnicodeError):
                reason = '请求失败'
            finally:
                exc.close()
            raise ValueError(f'HTTP {exc.code}：{reason}；409或预览过期须重新预览') from None


def discover(folder):
    expected = Path(os.environ.get('看板数据目录') or folder / '数据').resolve()
    for port in range(8765, 8776):
        url = f'http://127.0.0.1:{port}'
        try:
            with urlopen(url + '/health', timeout=.3) as r:
                value = json.load(r)
            if str(value.get('app', '')).startswith('competition-dashboard-') and Path(value['data_root']).resolve() == expected:
                return url
        except (OSError, ValueError, KeyError):
            continue
    raise ValueError('未找到本目录账户的服务；先运行比赛看板.exe，或用 --url 指定已核对的实例')


def enrich(client, payload):
    """补代码可确定的交易所和名称，不补价格、时间、数量。"""
    if payload.get('kind') == 'trades':
        rows = payload.get('rows', [])
    elif payload.get('kind') == 'snapshot':
        rows = payload.get('snapshot', {}).get('positions', [])
    else:
        return payload
    for row in rows:
        code = str(row.get('code', ''))
        if not re.fullmatch(r'\d{6}', code):
            raise ValueError('code须为保留前导零的六位字符串')
        exchange = next((v for keys, v in [('56', 'SH'), ('013', 'SZ'), ('489', 'BJ')] if code[0] in keys), None)
        if not exchange:
            raise ValueError('无法识别交易所，请核对六位代码')
        row.setdefault('exchange', exchange)
        if not row.get('name'):
            try:
                row['name'] = client.request('/api/lookup?' + urlencode({'symbol': row['exchange'] + ':' + code})).get('name') or code
            except (OSError, ValueError):
                row['name'] = code
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', help='本机地址，例 http://127.0.0.1:8765；默认匹配本目录账户')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('start', 'health', 'show', 'refresh'):
        sub.add_parser(name)
    m = sub.add_parser('market')
    m.add_argument('--section', choices=['overview', 'sectors', 'ranks', 'news', 'nav', 'huatai', 'summary', 'fund_flows'], default='overview')
    m.add_argument('--product-type', choices=['stock', 'etf', 'lof'], default='stock')
    m.add_argument('--sort', choices=['up', 'down', 'amount', 'turnover'], default='up')
    m.add_argument('--symbol')
    for name in ('kline', 'lookup'):
        p = sub.add_parser(name);p.add_argument('symbol', help='例 SH:510300 或 INDEX:NDX')
        if name == 'kline':
            p.add_argument('--period', choices=['day', 'm5'], default='day')
            p.add_argument('--adjustment', choices=['raw', 'qfq'], default='raw')
    for name in ('research','research-refresh'):
        p=sub.add_parser(name);p.add_argument('--topic',choices=['market_a','overseas','capital','events','product','sector','fund']);p.add_argument('--symbol');p.add_argument('--sector')
    p = sub.add_parser('preview');p.add_argument('--input', type=Path, required=True);p.add_argument('--ticket', type=Path, required=True)
    p = sub.add_parser('commit');p.add_argument('--ticket', type=Path, required=True)
    args = parser.parse_args(argv)
    folder = Path(__file__).resolve().parent
    if args.command == 'start':
        try:
            url = args.url or discover(folder)
        except ValueError:
            exe = folder / '比赛看板.exe'
            if not exe.is_file():
                raise ValueError('本目录缺少比赛看板.exe')
            subprocess.Popen([str(exe)], cwd=folder, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            for _ in range(80):
                try:
                    url = args.url or discover(folder);break
                except ValueError:
                    time.sleep(.25)
            else:
                raise ValueError('启动超时，请查看数据/看板服务.log')
    else:
        url = args.url or discover(folder)
    client = Client(url)
    if args.command in ('start', 'health'):
        result = client.request('/health')
    elif args.command == 'show':
        result = client.request('/api/view')
    elif args.command == 'refresh':
        result = client.request('/api/control', {'action': 'refresh', 'client': 'local-agent', 'interval': 5})
    elif args.command == 'market':
        query = {'section': args.section, 'product_type': args.product_type, 'sort': args.sort}
        if args.symbol:query['symbol'] = args.symbol
        result = client.request('/api/market?' + urlencode(query))
    elif args.command in ('research','research-refresh'):
        query={k:getattr(args,k) for k in ('topic','symbol','sector') if getattr(args,k) is not None}
        result=client.request('/api/research/refresh',query) if args.command=='research-refresh' else client.request('/api/research?'+urlencode(query))
    elif args.command in ('kline', 'lookup'):
        query = {'symbol': args.symbol}
        if args.command == 'kline':query.update(period=args.period, adjustment=args.adjustment)
        result = client.request('/api/' + args.command + '?' + urlencode(query))
    elif args.command == 'preview':
        payload = enrich(client, json.loads(args.input.read_text(encoding='utf-8-sig')))
        result = client.request('/api/import/preview', payload)
        args.ticket.write_text(json.dumps({'url': url, 'token': result['token'], 'expected_revision': result['revision']}, ensure_ascii=False), encoding='utf-8')
        result = {k: v for k, v in result.items() if k != 'token'}
        result['ticket'] = str(args.ticket)
    else:
        ticket = json.loads(args.ticket.read_text(encoding='utf-8-sig'))
        if ticket['url'] != url:
            raise ValueError('预览所属服务不同，请重新预览')
        result = client.request('/api/import/commit', {k: ticket[k] for k in ('token', 'expected_revision')})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'errors': [str(exc)]}, ensure_ascii=False))
        raise SystemExit(1)
