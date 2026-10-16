"""白名单源码交付可独立导入，禁止复制数据、认证及个人研究。"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'构建'))
from 准备仓库 import prepare


class RepositoryTests(unittest.TestCase):
    def test_source_is_standalone_and_contains_no_personal_data(self):
        app=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            target=prepare(app,Path(tmp)/'repo')
            for name in ('README.md','AGENTS.md','LICENSE','智能体工具.py','requirements-dev.txt','看板应用/构建/准备仓库.py'):
                self.assertTrue((target/name).is_file(),name)
            self.assertFalse(any(p.name in ('数据','投研','__pycache__') for p in target.rglob('*')))
            self.assertFalse(list(target.rglob('*.zip')))
            source=target/'看板应用/源码'
            result=subprocess.run([sys.executable,'-c',f'import sys;sys.path.insert(0,{str(source)!r});import 启动器,看板服务,指标;print(启动器.版本)'],cwd=target,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('3.0.1',result.stdout)
            self.assertFalse((target/'数据').exists())


if __name__=='__main__':unittest.main()
