import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码'))
#!/usr/bin/env python3
"""启动器验收：空数据根自举、已有账户不覆盖、数据根取值。不调用金融接口。"""
import json
import os
from pathlib import Path
import tempfile
import unittest

import 路径
import 启动器 as launcher


class DataRootTests(unittest.TestCase):
    def test_ensure_creates_baseline_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertTrue(launcher.ensure_data_root(root))
            account = json.loads((root / '账户记录/比赛账户.json').read_text(encoding='utf-8'))
            self.assertEqual(account['initial_cash'], '1000000.00')
            self.assertEqual(account['trades'], [])
            self.assertTrue((root / '账户记录/行情缓存.json').is_file())
            self.assertTrue((root / '账户记录/收益曲线.json').is_file())

    def test_ensure_keeps_existing_account(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            launcher.ensure_data_root(root)
            target = root / '账户记录/比赛账户.json'
            stamp = target.stat().st_mtime_ns
            self.assertFalse(launcher.ensure_data_root(root))
            self.assertEqual(target.stat().st_mtime_ns, stamp)

    def test_env_override_wins(self):
        with tempfile.TemporaryDirectory() as folder:
            old = os.environ.get('看板数据目录')
            os.environ['看板数据目录'] = folder
            try:
                self.assertEqual(路径.数据根(), Path(folder))
            finally:
                if old is None:
                    os.environ.pop('看板数据目录', None)
                else:
                    os.environ['看板数据目录'] = old

    def test_self_check_reports_paths_without_blocking(self):
        report = launcher.自检(Path('D:/空的'))
        self.assertEqual(report['数据根'], str(Path('D:/空的')))
        self.assertIn('资源根', report)
        self.assertIn('密钥', report)
        self.assertIn('技能目录', report)

    def test_every_subcommand_parses(self):
        parser = launcher.建解析器()
        self.assertEqual(parser.parse_args(['服务', '--port', '8799']).port, 8799)
        for name in ('版本', '检查', '同步'):
            self.assertEqual(parser.parse_args([name]).command, name)
        self.assertEqual(parser.parse_args(['台账', 'show']).rest, ['show'])
        self.assertEqual(parser.parse_args(['台账', 'sync', '--granularity', 'm5']).rest,
                         ['sync', '--granularity', 'm5'])

    def test_version_command_prints_without_side_effects(self):
        self.assertEqual(launcher.main(['版本']), 0)


if __name__ == '__main__':
    unittest.main()
