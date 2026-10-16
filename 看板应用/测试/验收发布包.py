import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码'))
#!/usr/bin/env python3
"""发布包端到端验收：启动、复用、页面在线不退出、关页退出、端口释放、_internal只读。

使用临时空账户，不读取个人台账；允许公开行情补数，无交易调用。用法：
python 看板应用/测试/验收发布包.py --发布目录 看板应用/发布/比赛看板
"""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import time
import tempfile
import urllib.error
import urllib.request


def 等健康(端口, 上限=40):
    for _ in range(上限):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{端口}/health', timeout=1) as response:
                return json.loads(response.read())
        except (OSError, ValueError):
            time.sleep(1)
    return None


def 目录摘要(路径):
    路径 = Path(路径)
    文件 = sorted(item for item in 路径.rglob('*') if item.is_file())
    摘要 = hashlib.sha256()
    for item in 文件:
        摘要.update(str(item.relative_to(路径)).encode())
        摘要.update(item.read_bytes())
    return {'文件数': len(文件), '字节': sum(item.stat().st_size for item in 文件),
            '哈希': 摘要.hexdigest()[:16]}


def _主流程(发布目录, 端口, 空闲, 页面保持, 用浏览器, 环境):
    发布目录 = Path(发布目录).resolve()
    可执行 = 发布目录 / '比赛看板.exe'
    结果 = {'发布目录': str(发布目录), '端口': 端口, '空闲秒': 空闲}
    if not 可执行.is_file():
        return {'通过': False, '问题': '未找到比赛看板.exe'}
    结果['_internal收到写入'] = None
    结果['_internal前'] = 目录摘要(发布目录 / '_internal')
    进程 = subprocess.Popen([str(可执行), '服务', '--port', str(端口), '--idle-exit', str(空闲), '--no-open'],env=环境)
    try:
        健康 = 等健康(端口)
        结果['健康'] = 健康
        if not 健康:
            return {'通过': False, '问题': '服务未在40秒内起来', **结果}
        数据根=Path(健康['data_root'])
        空账=json.loads((数据根/'账户记录/比赛账户.json').read_text(encoding='utf-8'))
        结果['同级独立空账户']=bool(数据根.resolve()==(发布目录/'数据').resolve()
            and 空账['initial_cash']=='1000000.00' and not 空账.get('trades')
            and not 空账.get('reconciliations') and not 空账.get('pending_orders'))
        首页 = urllib.request.urlopen(f'http://127.0.0.1:{端口}/', timeout=5).read().decode('utf-8')
        结果['首页字节'] = len(首页)
        结果['首页内嵌令牌'] = 'localToken=' in 首页
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{端口}/api/view', timeout=5)
            结果['无令牌访问'] = 200
        except urllib.error.HTTPError as 错误:
            结果['无令牌访问'] = 错误.code
            错误.close()
        第二次 = subprocess.run([str(可执行), '服务', '--port', str(端口), '--no-open'], timeout=90,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,env=环境)
        结果['第二次退出码'] = 第二次.returncode
        结果['复用时进程仍在'] = 进程.poll() is None
        结果['复用时健康pid不变'] = (等健康(端口) or {}).get('pid') == 健康.get('pid')
        if 用浏览器:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as 引擎:
                浏览器 = 引擎.chromium.launch(channel='msedge', headless=True)
                页 = 浏览器.new_page()
                页.goto(f'http://127.0.0.1:{端口}/')
                页.wait_for_function("document.getElementById('cash').textContent==='¥1,000,000.00'", timeout=20000)
                结果['空持仓页面']=页.locator('#positions .pos').count()==0
                页.locator('#import-open').click()
                页.locator('#import-kind').select_option('snapshot')
                结果['开账表单']=页.locator('#snapshot-fields').is_visible()
                页.locator('#import-close').click()
                time.sleep(页面保持)
                结果['页面在线时仍运行'] = 进程.poll() is None
                结果['页面读到端口'] = 页.locator('#local-address').inner_text()
                浏览器.close()
            上限 = 空闲 + 30
            for _ in range(上限):
                if 进程.poll() is not None:
                    break
                time.sleep(1)
            结果['关页后退出码'] = 进程.poll()
            结果['关页后等待秒'] = 上限
        else:
            结果['页面在线时仍运行'] = '未测'
        结果['退出后端口释放'] = 等健康(端口, 3) is None
        数据根 = Path(健康['data_root'])
        结果['数据根'] = str(数据根)
        结果['数据目录'] = sorted(item.relative_to(数据根).as_posix()
                                  for item in 数据根.rglob('*') if item.is_file())
        结果['_internal后'] = 目录摘要(发布目录 / '_internal')
        结果['_internal收到写入'] = 结果['_internal前'] != 结果['_internal后']
    finally:
        if 进程.poll() is None:
            进程.terminate()
            进程.wait(timeout=20)
    结果['通过'] = bool(
        结果.get('健康') and 结果.get('首页内嵌令牌') and 结果.get('无令牌访问') == 403
        and 结果.get('第二次退出码') == 0 and 结果.get('复用时进程仍在') and 结果.get('复用时健康pid不变')
        and 结果.get('页面在线时仍运行') in (True, '未测')
        and 结果.get('关页后退出码') == 0 and 结果.get('退出后端口释放') is True
        and 结果.get('_internal收到写入') is False
        and 结果.get('同级独立空账户') is True
        and (not 用浏览器 or (结果.get('空持仓页面') and 结果.get('开账表单')))
        and '账户记录/比赛账户.json' in (结果.get('数据目录') or []))
    return 结果


def 主流程(发布目录, 端口=8765, 空闲=15, 页面保持=40, 用浏览器=True):
    with tempfile.TemporaryDirectory(prefix='看板发布验收_') as 临时:
        # 真实搬运产物，不通过环境变量掩盖路径解析；父目录放异账户哨兵。
        原包=Path(发布目录).resolve();副本=Path(临时)/'比赛看板'
        if not (原包/'比赛看板.exe').is_file():return {'通过':False,'问题':'未找到比赛看板.exe'}
        副本.mkdir()
        shutil.copy2(原包/'比赛看板.exe',副本/'比赛看板.exe')
        shutil.copytree(原包/'_internal',副本/'_internal')
        哨兵=Path(临时)/'数据/账户记录/比赛账户.json';哨兵.parent.mkdir(parents=True)
        哨兵.write_text('{"parent_account_must_not_be_read":true}',encoding='utf-8')
        环境=dict(os.environ)
        环境.pop('看板数据目录',None)
        环境.pop('HT_APIKEY',None)
        return _主流程(副本,端口,空闲,页面保持,用浏览器,环境)


if __name__ == '__main__':
    解析 = argparse.ArgumentParser(description=__doc__)
    解析.add_argument('--发布目录', type=Path, default=Path('看板应用/发布/比赛看板'))
    解析.add_argument('--端口', type=int, default=8765)
    解析.add_argument('--空闲', type=int, default=15)
    解析.add_argument('--页面保持', type=int, default=40)
    解析.add_argument('--不用浏览器', action='store_true')
    参数 = 解析.parse_args()
    报告 = 主流程(参数.发布目录, 参数.端口, 参数.空闲, 参数.页面保持, not 参数.不用浏览器)
    print(json.dumps(报告, ensure_ascii=False, indent=2))
    raise SystemExit(0 if 报告.get('通过') else 1)
