"""拒绝串市场、伪新鲜和录账隐式重建；全部使用临时账户。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码'))
import importlib
import tempfile
import unittest
from datetime import datetime
import 账户核心 as core
import 账户台账 as ledger


class ContractTests(unittest.TestCase):
    def test_symbol_and_decimal_contract(self):
        c = importlib.import_module('数据契约')
        self.assertNotEqual(c.validate_symbol('SH:000001'), c.validate_symbol('SZ:000001'))
        for bad in ('../../x', 'SH:123', 'US:http://x', 'HK:700'):
            with self.assertRaises(ValueError): c.validate_symbol(bad)
        self.assertEqual(c.decimal_text('4.242'), '4.242')
        for bad in ('NaN', 'Infinity'):
            with self.assertRaises(ValueError): c.decimal_text(bad)

    def test_freshness_uses_provider_clock_not_fetch_clock(self):
        c = importlib.import_module('数据契约')
        ds = c.dataset('quotes', {}, 'test', source_as_of='2026-10-15T10:00:00+08:00')
        clock = datetime.fromisoformat('2026-10-15T11:00:00+08:00')
        self.assertEqual(c.freshness(ds, clock, 'open'), 'stale')
        ds['source_as_of']='2026-10-15T15:00:00+08:00'
        self.assertEqual(c.freshness(ds, datetime.fromisoformat('2026-10-15T16:00:00+08:00'), 'closed'), 'ok')
        ds['source_as_of'] = None
        self.assertEqual(c.freshness(ds, clock, 'open'), 'unknown')

    def test_record_only_writes_facts_and_observer_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / '账户.json'
            ledger.init(p, started='2026-10-10T00:00:00+08:00')
            ledger.render(p)
            before = {f.name:f.read_bytes() for f in p.parent.iterdir() if f != p}
            ledger.record(p, dict(id='x',time=None,trade_date='2026-10-15',code='510300',exchange='SH',
                name='ETF',side='buy',quantity=100,price='4.242',fee=None,
                confirmation={'quantity':'confirmed','price':'confirmed'}))
            self.assertEqual(before, {f.name:f.read_bytes() for f in p.parent.iterdir() if f != p})
            core.observe_account(p)
            self.assertEqual(core.load_nav(p)['observations'][-1]['total_assets'], None)
            self.assertEqual(core.load_nav(p)['account_revision'], core.account_revision(core.load_account(p)))

    def test_read_corrupt_cache_never_moves_or_writes_file(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'账户.json'
            ledger.init(p)
            core.cache_path(p).write_text('{broken', encoding='utf-8')
            before={f.name:f.read_bytes() for f in p.parent.iterdir()}
            self.assertEqual(core.view_model(p)['summary']['total_assets'],'1000000.00')
            self.assertEqual(before,{f.name:f.read_bytes() for f in p.parent.iterdir()})


if __name__ == '__main__': unittest.main()
