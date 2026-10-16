"""录入原子性、幂等、并发冲突及未知字段；不使用正式账户。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码'))
import importlib
import tempfile
import unittest
import 账户核心 as core
import 账户台账 as ledger


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'账户.json';ledger.init(self.path)
        self.payload={'kind':'trades','rows':[dict(id='x',code='510300',exchange='SH',name='ETF',side='buy',
            quantity=100,price='4.242',fee=None,time=None)]}

    def tearDown(self):self.tmp.cleanup()

    def test_preview_has_no_writes_and_commit_only_changes_account(self):
        m=importlib.import_module('账户录入')
        before={p.name:p.read_bytes() for p in self.path.parent.iterdir()}
        result=m.preview_import(core.load_account(self.path),self.payload)
        self.assertFalse(result['errors'])
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.path.parent.iterdir()})
        m.commit_import(self.path,self.payload,result['revision'])
        facts=core.load_account(self.path)
        self.assertEqual(facts['trades'][0]['price'],'4.242')
        # 表单留空费用＝按赛事规则（沪深万3）推定，不再要求用户查手续费。
        self.assertEqual(facts['trades'][0]['fee'],'0.13')
        self.assertEqual(facts['trades'][0]['confirmation']['fee'],'rule')
        for name,body in before.items():
            if name!=self.path.name:self.assertEqual((self.path.parent/name).read_bytes(),body)

    def test_duplicates_do_not_change_account_bytes(self):
        m=importlib.import_module('账户录入')
        m.commit_import(self.path,self.payload,core.account_revision(core.load_account(self.path)))
        before=self.path.read_bytes()
        m.commit_import(self.path,self.payload,core.account_revision(core.load_account(self.path)))
        self.assertEqual(before,self.path.read_bytes())

    def test_old_revision_and_partial_error_never_overwrite(self):
        m=importlib.import_module('账户录入');rev=core.account_revision(core.load_account(self.path))
        ledger.pending(self.path,[])
        # 即使同秒空委托不改变内容，用真实事实更改模拟另一位编辑者。
        other=core.load_account(self.path);other['baseline_source']='另一位编辑者';core.save_account(self.path,other)
        before=self.path.read_bytes()
        with self.assertRaises(m.RevisionConflict):m.commit_import(self.path,self.payload,rev)
        bad={'kind':'trades','rows':[self.payload['rows'][0],dict(self.payload['rows'][0],id='bad',quantity=-1)]}
        r=m.preview_import(core.load_account(self.path),bad)
        self.assertTrue(r['errors'])
        with self.assertRaises(ValueError):m.commit_import(self.path,bad,core.account_revision(core.load_account(self.path)))
        self.assertEqual(before,self.path.read_bytes())

    def test_csv_empty_fields_are_unknown_and_foreign_currency_is_rejected(self):
        m=importlib.import_module('账户录入')
        csv='id,time,code,exchange,name,side,quantity,price,fee\nx,,510300,SH,ETF,buy,100,4.242,\n'
        r=m.preview_import(core.load_account(self.path),{'kind':'trades','csv':csv})
        self.assertFalse(r['errors'])
        # 空费用列按规则推定；空时间列仍保持未知。
        self.assertEqual(r['normalized']['trades'][0]['fee'],'0.13')
        self.assertIsNone(r['normalized']['trades'][0]['time'])
        self.assertEqual(r['normalized']['trades'][0]['confirmation']['time'],'unknown')
        r=m.preview_import(core.load_account(self.path),{'kind':'trades','rows':[dict(self.payload['rows'][0],exchange='HK',code='00700')]})
        self.assertTrue(r['errors'])

    def test_minimal_form_fields_are_enough(self):
        """最小写入：代码、方向、数量、价格、时间；名称缺失时用代码占位。"""
        m=importlib.import_module('账户录入')
        row=dict(code='159920',exchange='SZ',name='159920',side='buy',quantity=40000,price='1.418',time=core.now())
        r=m.preview_import(core.load_account(self.path),{'kind':'trades','rows':[row]})
        self.assertFalse(r['errors'])
        trade=r['normalized']['trades'][0]
        self.assertEqual(trade['amount'],'56720.00')
        self.assertEqual(trade['fee'],'17.02')
        self.assertEqual(trade['confirmation'],{'execution':'confirmed','quantity':'confirmed',
            'price':'confirmed','time':'confirmed','fee':'rule'})

    def test_automatic_id_uses_normalized_price_and_time(self):
        m=importlib.import_module('账户录入')
        first=dict(self.payload['rows'][0]);first.pop('id');first['time']=core.now()
        payload={'kind':'trades','rows':[first]}
        m.commit_import(self.path,payload,core.account_revision(core.load_account(self.path)))
        second=dict(first,price='4.2420',time=first['time'].replace('+08:00',''))
        result=m.preview_import(core.load_account(self.path),{'kind':'trades','rows':[second]})
        self.assertFalse(result['errors'])
        self.assertEqual(result['changes'],[])


if __name__=='__main__':unittest.main()
