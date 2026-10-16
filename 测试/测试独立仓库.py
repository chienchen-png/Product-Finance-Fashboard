"""白名单源码交付可独立导入，禁止复制数据、认证及个人研究。"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import re
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'构建'))
from 准备仓库 import prepare


class RepositoryTests(unittest.TestCase):
    def test_source_is_standalone_and_contains_no_personal_data(self):
        app=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            target=prepare(app,Path(tmp)/'repo')
            for name in ('README.md','LICENSE','requirements.txt','requirements-dev.txt','构建/准备仓库.py',
                         '构建/比赛看板.spec','文档/数据来源与接口.md','源码/启动器.py','测试/测试账户台账.py'):
                self.assertTrue((target/name).is_file(),name)
            for name in ('AGENTS.md','智能体工具.py','看板应用'):
                self.assertFalse((target/name).exists(),name)
            self.assertFalse(any(p.name in ('数据','投研','__pycache__') for p in target.rglob('*')))
            self.assertFalse(list(target.rglob('*.zip')))
            for doc in target.rglob('*.md'):
                for link in re.findall(r'\]\(([^)]+)\)',doc.read_text('utf-8')):
                    if '://' not in link and not link.startswith('#'):self.assertTrue((doc.parent/link.split('#')[0]).exists(),(doc,link))
            source=target/'源码'
            result=subprocess.run([sys.executable,'-c',f'import sys;sys.path.insert(0,{str(source)!r});import 启动器,看板服务,指标;print(启动器.版本)'],cwd=target,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('3.1.1',result.stdout)
            self.assertFalse((target/'数据').exists())


if __name__=='__main__':unittest.main()
