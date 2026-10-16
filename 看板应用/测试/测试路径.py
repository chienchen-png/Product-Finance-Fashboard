import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码'))
#!/usr/bin/env python3
"""路径解析验收：资源根与数据根取值规则，不触碰账户数据。"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class ResolveTests(unittest.TestCase):
    def test_standalone_source_uses_same_data_as_root_exe(self):
        import 路径
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'比赛看板.exe').write_bytes(b'marker')
            with patch.dict(os.environ,{},clear=True),patch.object(路径,'项目根',return_value=root),patch.object(路径,'打包态',return_value=False):
                self.assertEqual(路径.数据根(),root/'数据')
            self.assertFalse((root/'数据').exists())

    def test_personal_source_keeps_personal_application_data(self):
        import 路径
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=root/'看板应用';app.mkdir();(app/'比赛看板.exe').write_bytes(b'marker')
            with patch.dict(os.environ,{},clear=True),patch.object(路径,'项目根',return_value=root),patch.object(路径,'应用根',return_value=app),patch.object(路径,'打包态',return_value=False):
                self.assertEqual(路径.数据根(),app/'数据')
    def test_env_wins_over_packaging(self):
        import 路径
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(路径.解析数据根(folder, True, Path('D:/应用'), Path('D:/项目')), Path(folder))
            self.assertEqual(路径.解析数据根(folder, False, Path('D:/应用'), Path('D:/项目')), Path(folder))

    def test_frozen_uses_exe_folder_data_when_account_present(self):
        import 路径
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / '数据/账户记录').mkdir(parents=True)
            self.assertEqual(路径.解析数据根(None, True, base, Path('D:/项目')), base / '数据')

    def test_frozen_falls_back_to_data_folder(self):
        import 路径
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            self.assertEqual(路径.解析数据根(None, True, base, Path('D:/项目')), base / '数据')

    def test_frozen_never_reads_ancestor_account(self):
        import 路径
        with tempfile.TemporaryDirectory() as folder:
            application = Path(folder) / '项目/看板应用'
            (application / '数据/账户记录').mkdir(parents=True)
            base = application / '发布' / '比赛看板'
            base.mkdir(parents=True)
            self.assertEqual(路径.解析数据根(None, True, base, Path('D:/别的')), base / '数据')

    def test_source_mode_uses_application_data(self):
        import 路径
        application = Path('D:/项目/看板应用')
        self.assertEqual(路径.解析数据根(None, False, Path('D:/应用'), application), application / '数据')

    def test_resource_prefers_data_root_then_falls_back(self):
        import 路径
        name = '看板应用/源码/账户看板模板.html'
        with tempfile.TemporaryDirectory() as folder:
            old = os.environ.get('看板数据目录')
            os.environ['看板数据目录'] = folder
            try:
                self.assertEqual(路径.资源路径(name), 路径.资源根() / Path(name))
                target = Path(folder) / name
                target.parent.mkdir(parents=True)
                target.write_text('x', encoding='utf-8')
                self.assertEqual(路径.资源路径(name), target)
            finally:
                if old is None:
                    os.environ.pop('看板数据目录', None)
                else:
                    os.environ['看板数据目录'] = old


if __name__ == '__main__':
    unittest.main()
