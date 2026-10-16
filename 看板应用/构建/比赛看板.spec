# -*- mode: python ; coding: utf-8 -*-
"""onedir 打包配置：只有启动器进包，账户数据留在数据根。"""
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

应用根 = Path(SPECPATH).resolve().parent
源码根 = 应用根 / '源码'

a = Analysis(
    [str(源码根 / '启动器.py')],
    pathex=[str(源码根)],
    binaries=[],
    datas=[
        (str(源码根 / '账户看板模板.html'), '看板应用/源码'),
        (str(源码根 / '市场看板.js'), '看板应用/源码'),
        (str(源码根 / '账户录入.js'), '看板应用/源码'),
        (str(源码根 / '图表依赖'), '看板应用/源码/图表依赖'),
        (str(应用根 / '资源/A股交易日历.json'), '看板应用/资源'),
        (str(应用根 / '资源/官方技能版本清单.json'), '看板应用/资源'),
    ] + collect_data_files('tzdata'),
    hiddenimports=['requests', 'urllib3', 'certifi', 'charset_normalizer', 'idna','tzdata'],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'pydoc', 'doctest', 'test', 'numpy', 'pandas', 'playwright'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='比赛看板',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(应用根 / '构建/看板图标.ico'),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='比赛看板',
)
