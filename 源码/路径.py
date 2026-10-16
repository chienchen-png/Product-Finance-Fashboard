#!/usr/bin/env python3
"""资源根与数据根的唯一解析点：只读环境与文件系统，不创建目录。"""
import os
from pathlib import Path
import sys

环境键 = '看板数据目录'


def 源码根():
    return Path(__file__).resolve().parent


def 应用根():
    return 源码根().parent


def 项目根():
    return 应用根().parent


def 打包态():
    return bool(getattr(sys, 'frozen', False))


def 资源根():
    """内嵌资源目录：打包态取解包目录，源码态取应用根（本人项目为`看板应用`，独立仓库为仓库根）。"""
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS)
    return 应用根()


def 解析数据根(环境值=None, 打包=None, exe目录=None, 源码根目录=None):
    """纯函数：按环境值、打包位置、源码根依次解析，不创建目录。

    打包态只用exe同级数据，不扫描父目录。
    源码态固定使用应用目录内的数据。
    """
    if 环境值:
        return Path(环境值).expanduser()
    if 打包 is None:
        打包 = 打包态()
    if 打包:
        base = Path(exe目录 or Path(sys.executable).parent)
        return base / '数据'
    return Path(源码根目录 or 应用根()) / '数据'


def 数据根():
    override = os.environ.get(环境键)
    if override:
        return Path(override).expanduser()
    # 源码态与同级EXE共用应用目录数据；打包态只看EXE同级。
    return 解析数据根(None, 源码根目录=应用根())


def 资源路径(相对):
    """数据根内的同名文件优先，缺文件时回退打包内嵌资源。"""
    target = 数据根() / Path(相对)
    return target if target.exists() else 资源根() / Path(相对)
