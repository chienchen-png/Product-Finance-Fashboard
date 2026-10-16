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
        shutil.copy2(source, dest)
    runtime = ['启动器.py', '路径.py', '账户核心.py', '账户台账.py', '账户录入.py',
               '行情同步.py', '市场同步.py', '看板服务.py', '数据契约.py', '指标.py',
               '账户看板模板.html', '账户录入.js', '市场看板.js', '页面导航.js', '投研看板.js', '产品分析.js', '市场摘要.py', '投研缓存.py', '华泰资料.py', '环境检查.py', '华泰接口验收.py', '研究/__init__.py', '研究/数据.py']
    for name in runtime:
        copy(app / '源码' / name, '看板应用/源码/' + name)
    for folder in ('数据源', '图表依赖'):
        for source in (app / '源码' / folder).rglob('*'):
            if source.is_file() and '__pycache__' not in source.parts:
                copy(source, '看板应用/源码/' + source.relative_to(app / '源码').as_posix())
    for name in ('A股交易日历.json', '官方技能版本清单.json'):
        copy(app / '资源' / name, '看板应用/资源/' + name)
    copy(app/'构建/接口说明.md','看板应用/规划/接口说明.md')
    obsolete=target/'看板应用/规划/华泰接入验收.md'
    if obsolete.is_file():obsolete.unlink()
    for source in (app / '测试').glob('*.py'):
        if source.name.startswith('测试研究') or source.name == '测试看板交互.py':
            continue
        copy(source, '看板应用/测试/' + source.name)
    for name in ('构建发布.ps1', '比赛看板.spec', '看板图标.ico', '发布说明.md',
                 '智能体工具.py', '准备仓库.py', '开源许可.txt', '接口说明.md'):
        copy(app / '构建' / name, '看板应用/构建/' + name)
    copy(app / '构建/发布说明.md', 'README.md')
    copy(app / '构建/智能体工具.py', '智能体工具.py')
    copy(app / '构建/开源许可.txt', 'LICENSE')
    (target / '.gitignore').write_text('数据/\n**/数据/\n*.log\n*.log.1\n*.预览.json\n*成交.json\n*快照.json\n__pycache__/\n.venv/\n看板应用/构建缓存/\n看板应用/发布/\n', encoding='utf-8')
    (target / 'requirements.txt').write_text('requests>=2.32,<3\ntzdata>=2026.1\n', encoding='utf-8')
    (target / 'requirements-dev.txt').write_text('-r requirements.txt\npyinstaller==6.22.3\nplaywright>=1.55,<2\n', encoding='utf-8')
    (target / 'AGENTS.md').write_text('''# 智能体入口

先读README。服务仅在本机运行；使用`python 智能体工具.py --help`，通过本机API操作，禁止直接覆盖账户JSON或修改行情缓存。

- 先`health`核对data_root，再`show`读取账户；行情用`market`、`kline`，刷新用`refresh`。
- 用户已明确确认的手机成交才可入账。仅计划、挂单、建议不算成交；未知价格、数量、时间不猜。
- 首次已有持仓用snapshot开账，无须补此前交易；随后只录快照后的成交。
- 写入先`preview --input 文件 --ticket 临时.预览.json`，检查变更，再`commit --ticket 临时.预览.json`。预览不写账；过期或409须重读重新预览，禁止绕过版本冲突。
- 一个账户一个本地数据目录。认证和预览票据不提交Git，不打印会话令牌；不连接真实交易，不自动下单。
- README的“一句话交给智能体”用于部署。程序内置华泰只读适配，配置自己的HT_APIKEY可用华泰主报价及研究资料；无密钥保留公开补充源。华泰资料为供应商AI生成，待核验；用research读取缓存、research-refresh显式更新主题，与网页共享版本，不直接作为确认事实或交易信号。
''', encoding='utf-8')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', type=Path)
    args = parser.parse_args()
    print(prepare(Path(__file__).resolve().parents[1], args.target))
