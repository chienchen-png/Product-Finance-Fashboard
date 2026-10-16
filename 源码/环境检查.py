#!/usr/bin/env python3
"""设备环境检查与官方技能调度：默认离线只读，--install下载，--run调用，--online只读联网。"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

import 路径

ROOT = 路径.数据根()
MANIFEST = 路径.资源路径('资源/官方技能版本清单.json')
SKILL_ROOTS = (Path.home() / '.agents/skills', Path.home() / '.codex/skills')


def say(text=''):
    print(text, flush=True)


def manifest():
    return json.loads(MANIFEST.read_text(encoding='utf-8'))


def skill_folder(name):
    for base in SKILL_ROOTS:
        folder = base / name
        if folder.is_dir():
            return folder
    return None


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(folder, files):
    """返回(是否全部匹配, 不一致文件列表)。"""
    bad = [name for name, wanted in files.items()
           if not (folder / name).is_file() or digest(folder / name) != wanted]
    return not bad, bad


def api_key_source():
    if os.environ.get('HT_APIKEY'):
        return '环境变量HT_APIKEY'
    for candidate in (Path.home() / '.htsc-skills/config',):
        if candidate.is_file():
            text = candidate.read_text(encoding='utf-8', errors='replace')
            if any(line.strip().startswith('HT_APIKEY=') and line.split('=', 1)[1].strip()
                   for line in text.splitlines()):
                return '用户目录.htsc-skills/config'
    return None


def requests_state():
    try:
        import requests  # noqa: F401
        return '已安装'
    except ImportError:
        return '缺失'


def ensure_requests():
    if requests_state() == '已安装':
        return True
    say('缺少requests，尝试安装到当前Python环境…')
    result = subprocess.run([sys.executable, '-m', 'pip', 'install', 'requests'], check=False)
    if result.returncode != 0 or requests_state() != '已安装':
        say('requests安装失败；技能脚本无法运行，请先解决该依赖。')
        return False
    return True


def download_bytes(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'codex-env-check'})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def extract_checked(blob, item, target):
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = archive.namelist()
        for name in item['文件']:
            member = name if name in names else next(
                (x for x in names if x.endswith('/' + name)), None)
            if member is None:
                raise ValueError('压缩包内未找到 ' + name)
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, open(destination, 'wb') as out:
                shutil.copyfileobj(source, out)


def install(name):
    """按清单下载并校验技能；已有且一致则跳过，不一致则不覆盖。"""
    item = next((x for x in manifest()['技能包'] if x['名称'] == name), None)
    if item is None:
        say(f'清单里没有技能 {name}，不下载。')
        return 1
    folder = skill_folder(name)
    if folder:
        matched, bad = verify(folder, item['文件'])
        if matched:
            say(f'{name}：已安装且哈希一致，跳过。')
            return 0
        say(f'{name}：已存在但{len(bad)}个文件与清单不一致（{", ".join(bad)}）。')
        say('按项目规则不擅自覆盖。请先比对官方升级与来源，确认后手动更新清单或目录。')
        return 1
    target = SKILL_ROOTS[0] / name
    say(f'{name}：下载 {item["来源"]}')
    try:
        blob = download_bytes(item['来源'])
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        say(f'{name}：下载失败（{type(exc).__name__}），保持待安装状态。')
        return 1
    actual = hashlib.sha256(blob).hexdigest()
    if actual != item['压缩包SHA256']:
        say(f'{name}：压缩包哈希不符，已停止安装。实际 {actual}')
        return 1
    temp = Path(tempfile.mkdtemp(prefix='htsc-skill-'))
    try:
        extract_checked(blob, item, temp)
        matched, bad = verify(temp, item['文件'])
        if not matched:
            say(f'{name}：解压后文件校验失败（{", ".join(bad)}），未写入用户目录。')
            return 1
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.copytree(temp, target, dirs_exist_ok=True)
        else:
            temp.rename(target)
        say(f'{name}：安装完成 → {target}')
        return 0
    finally:
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)


def check():
    data = manifest()
    report = {'python': sys.version.split()[0], 'requests': requests_state(),
              'HT_APIKEY': api_key_source() or '缺失', '技能': {}}
    pending = []
    for item in data['技能包']:
        name = item['名称']
        folder = skill_folder(name)
        if not folder:
            report['技能'][name] = '待安装'
            pending.append(name)
            continue
        matched, bad = verify(folder, item['文件'])
        report['技能'][name] = f'已安装（{folder}）' + ('' if matched else f'；{len(bad)}个文件与清单不符')
    report['待安装'] = pending
    say(json.dumps(report, ensure_ascii=False, indent=2))
    say()
    say(f'Python {report["python"]}｜requests {report["requests"]}｜HT_APIKEY {report["HT_APIKEY"]}')
    if pending:
        say('待安装：' + '、'.join(pending) + '；需要时运行 python 看板应用/源码/环境检查.py --install --skill <名称>')
    else:
        say('清单内技能齐备。')
    say('本检查默认不联网、不下单、不撤单；联网只读检查用 --online。')
    return 0


def run_skill(name, tool, extra):
    folder = skill_folder(name)
    if not folder:
        say(f'{name} 未安装，先按清单下载。')
        if install(name) != 0:
            return 1
        folder = skill_folder(name)
    item = next((x for x in manifest()['技能包'] if x['名称'] == name), None)
    if item:
        matched, bad = verify(folder, item['文件'])
        if not matched:
            say(f'{name} 有{len(bad)}个文件与清单不一致（{", ".join(bad)}），先核对版本再调用。')
            return 3
    script = next((folder / n for n in sorted(item['文件']) if n.endswith('.py')), None) if item else None
    if script is None or not script.is_file():
        say(f'{name} 未找到可执行脚本。')
        return 1
    if not ensure_requests():
        return 1
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    say(f'调用 {name} {tool}（实际脚本 {script}）')
    return subprocess.run([sys.executable, str(script), tool, *extra], env=env, check=False).returncode


def online():
    if not ensure_requests():
        return 1
    say('只读联网检查：默认模拟组资金 + 601688/SH 报价；不下单、不撤单。')
    for tool, extra in (('getAccountBalance', []), ('getQuote', ['--stock-code', '601688', '--exchange', 'SH'])):
        code = run_skill('a-share-paper-trading', tool, extra)
        if code != 0:
            return code
    return 0


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true', help='下载缺失技能到用户目录')
    parser.add_argument('--skill', help='技能目录名，逗号分隔；省略时处理清单内全部')
    parser.add_argument('--run', nargs=2, metavar=('技能', '工具'), help='调用技能工具')
    parser.add_argument('--online', action='store_true', help='只读联网检查资金与行情')
    opts, extra = parser.parse_known_args()
    try:
        if opts.run:
            return run_skill(opts.run[0], opts.run[1], [a for a in extra if a != '--'])
        if opts.install:
            names = [x.strip() for x in opts.skill.split(',')] if opts.skill \
                else [x['名称'] for x in manifest()['技能包']]
            codes = [install(name) for name in names]
            return max(codes) if codes else 0
        if opts.online:
            return online()
        return check()
    except (OSError, ValueError, KeyError, urllib.error.URLError) as exc:
        say('环境检查失败：' + (str(exc) if isinstance(exc, (ValueError, KeyError)) else type(exc).__name__))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
