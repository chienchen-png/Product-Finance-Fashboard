#!/usr/bin/env python3
"""比赛看板唯一入口：默认无窗口起本机服务并打开浏览器，另带台账等子命令。"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import threading
import webbrowser

if getattr(sys, 'frozen', False):
    工具目录 = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent)) / '源码'
else:
    工具目录 = Path(__file__).resolve().parent
if str(工具目录) not in sys.path:
    sys.path.insert(0, str(工具目录))

import 路径

数据根 = 路径.数据根()
os.environ.setdefault(路径.环境键, str(数据根))

import 账户台账 as ledger
import 看板服务 as service

版本 = '3.1.1'
日志名 = '看板服务.log'
日志上限 = 2 * 1024 * 1024


def 写日志(根, 文本):
    path = Path(根) / 日志名
    try:
        if path.exists() and path.stat().st_size > 日志上限:
            path.replace(path.with_name(日志名 + '.1'))
        with path.open('a', encoding='utf-8') as out:
            out.write(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} {文本}\n')
    except OSError:
        pass


def 提示(文本):
    """只在异常路径调用，正常启动不弹窗。"""
    line = str(文本)
    if sys.stdout is not None or sys.stderr is not None:
        try:
            print(line, file=sys.stderr if sys.stderr is not None else sys.stdout)
        except Exception:
            pass
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, line, '比赛看板', 0x10)
    except Exception:
        pass


def 自检(根):
    """环境事实汇总：缺技能或密钥只报告，不阻断启动。"""
    根 = Path(根)
    账户 = 根 / '账户记录/比赛账户.json'
    技能 = next((base / 'a-share-paper-trading' for base in
                 (Path.home() / '.agents/skills', Path.home() / '.codex/skills')
                 if (base / 'a-share-paper-trading').is_dir()), None)
    try:
        import requests  # noqa: F401
        依赖 = True
    except ImportError:
        依赖 = False
    try:
        from 数据源.华泰 import key as 华泰密钥
        有密钥 = bool(华泰密钥())
    except (ImportError, OSError):
        有密钥 = bool(os.environ.get('HT_APIKEY'))
    return {'版本': 版本, '打包': 路径.打包态(), '数据根': str(根), '资源根': str(路径.资源根()),
            '账户文件': str(账户), '账户存在': 账户.is_file(), '技能目录': str(技能) if 技能 else None,
            '密钥': 有密钥,
            'requests': 依赖}


def ensure_data_root(根):
    """空数据根自举100万基线；已有账户不覆盖。返回是否新建。"""
    账户 = Path(根) / '账户记录/比赛账户.json'
    if 账户.exists():
        return False
    ledger.init(账户)
    return True


def 起服务(根, args):
    根 = Path(根)
    ports = range(args.port, args.port + 1) if args.port else range(8765, 8776)
    action, port = service.pick_port(根, ports)
    url = f'http://127.0.0.1:{port}/'
    if action == 'reuse':
        if not args.no_open:
            webbrowser.open(url)
        写日志(根, f'复用既有服务 {url}')
        return 0
    server = service.create_server(根 / '账户记录/比赛账户.json', port)
    server.updater.idle_exit = args.idle_exit
    server.updater.startup_idle_exit = args.startup_idle_exit
    server.updater.on_idle = server.shutdown
    with server.updater.lock:
        # 启动后先同步一次行情；是否继续定时轮询仍由网页上的联动开关决定。
        server.updater.initial = True
    threading.Thread(target=server.updater.loop, daemon=True).start()
    if not args.no_open:
        webbrowser.open(url)
    写日志(根, f'服务启动 {url} 空闲退出{args.idle_exit}秒 自检{json.dumps(自检(根), ensure_ascii=False)}')
    try:
        server.serve_forever()
    finally:
        server.updater.shutdown.set()
        server.server_close()
        写日志(根, '服务停止')
    return 0


def 建解析器():
    parser = argparse.ArgumentParser(prog='比赛看板', description=__doc__)
    sub = parser.add_subparsers(dest='command')
    serve = sub.add_parser('服务', help='起本机服务并打开浏览器')
    serve.add_argument('--port', type=int, default=None, help='起始端口；默认从8765顺延')
    serve.add_argument('--idle-exit', type=int, default=service.IDLE_EXIT_SECONDS)
    serve.add_argument('--startup-idle-exit', type=int, default=service.STARTUP_IDLE_EXIT_SECONDS)
    serve.add_argument('--no-open', action='store_true', help='只起服务，不打开浏览器')
    sub.add_parser('版本')
    sub.add_parser('检查')
    sub.add_parser('同步')
    ledger_cmd = sub.add_parser('台账', help='透传账户台账子命令')
    ledger_cmd.add_argument('rest', nargs=argparse.REMAINDER)
    return parser


def _main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith('-'):
        argv = ['服务'] + argv
    parser = 建解析器()
    args = parser.parse_args(argv)
    if args.command == '版本':
        print(版本)
        return 0
    if args.command == '检查':
        print(json.dumps(自检(数据根), ensure_ascii=False, indent=2))
        return 0
    if args.command == '台账':
        sys.argv = ['账户台账'] + list(args.rest)
        return ledger.main()
    if args.command == '同步':
        report = ledger.sync(数据根 / '账户记录/比赛账户.json')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2 if report['报价失败'] or report['K线失败'] else 0
    if ensure_data_root(数据根):
        写日志(数据根, '已按100万基线新建账户')
    return 起服务(数据根, args)


def main(argv=None):
    try:
        return _main(argv)
    except SystemExit:
        raise
    except BaseException as error:
        try:
            根 = 路径.数据根()
        except Exception:
            根 = Path('.')
        写日志(根, f'异常 {type(error).__name__}: {error}')
        提示(f'比赛看板启动失败：{type(error).__name__}: {error}\n详见 {Path(根) / 日志名}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
