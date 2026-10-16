"""发布可运行、可阅读及可重建的独立仓库；只复制白名单，不复制账户或认证。"""
from pathlib import Path
import argparse
import shutil


def prepare(app, target):
    app, target = Path(app).resolve(), Path(target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    def copy(source, relative):
        dest = target / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() == dest.resolve():
            return
        shutil.copy2(source, dest)
    def seed(*candidates):
        """同一份资料在本人项目（构建内）与独立仓库（根目录）位置不同，取第一个存在的。"""
        for relative in candidates:
            path = app / relative
            if path.is_file():
                return path
        raise FileNotFoundError('缺少源文件：' + ' 或 '.join(candidates))
    runtime = ['启动器.py', '路径.py', '账户核心.py', '账户台账.py', '账户录入.py',
               '行情同步.py', '市场同步.py', '看板服务.py', '数据契约.py', '指标.py',
               '账户看板模板.html', '账户录入.js', '市场看板.js', '页面导航.js', '投研看板.js', '产品分析.js', '市场摘要.py', '投研缓存.py', '华泰资料.py', '环境检查.py', '华泰接口验收.py', '研究/__init__.py', '研究/数据.py']
    for name in runtime:
        copy(app / '源码' / name, '源码/' + name)
    for folder in ('数据源', '图表依赖'):
        for source in (app / '源码' / folder).rglob('*'):
            if source.is_file() and '__pycache__' not in source.parts:
                copy(source, '源码/' + source.relative_to(app / '源码').as_posix())
    for name in ('A股交易日历.json', '官方技能版本清单.json'):
        copy(app / '资源' / name, '资源/' + name)
    copy(seed('构建/接口说明.md', '文档/数据来源与接口.md'), '文档/数据来源与接口.md')
    for source in (app / '测试').glob('*.py'):
        if source.name.startswith('测试研究') or source.name in ('测试看板交互.py', '测试智能体工具.py'):
            continue
        copy(source, '测试/' + source.name)
    for name in ('构建发布.ps1', '比赛看板.spec', '看板图标.ico', '准备仓库.py'):
        copy(app / '构建' / name, '构建/' + name)
    copy(seed('配置.json'), '配置.json')
    copy(seed('构建/发布说明.md', 'README.md'), 'README.md')
    copy(seed('构建/开源许可.txt', 'LICENSE'), 'LICENSE')
    (target / '.gitignore').write_text('数据/\n**/数据/\n*.log\n*.log.1\n*.预览.json\n*成交.json\n*快照.json\n__pycache__/\n.venv/\n构建缓存/\n发布/\n', encoding='utf-8')
    (target / 'requirements.txt').write_text('requests>=2.32,<3\ntzdata>=2026.1\n', encoding='utf-8')
    (target / 'requirements-dev.txt').write_text('-r requirements.txt\npyinstaller==6.22.3\nplaywright>=1.55,<2\n', encoding='utf-8')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', type=Path)
    args = parser.parse_args()
    print(prepare(Path(__file__).resolve().parents[1], args.target))
