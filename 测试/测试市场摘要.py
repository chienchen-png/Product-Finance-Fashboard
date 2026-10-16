import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码'))
import unittest
from 市场摘要 import build
from 华泰资料 import parse_fund_answer
from 数据契约 import dataset
import json


class SummaryTests(unittest.TestCase):
    def inputs(self):
        quotes=[dict(symbol=s,amount=a,amount_unit='CNY',source='test',source_as_of='2026-10-16T15:00:00+08:00') for s,a in [('SH:000001','100'),('SZ:399001','200'),('SZ:399006','90')]]
        return dataset('overview',quotes,'test'),dataset('sectors',[dict(change_pct=x) for x in ('.01','-.02','0',None)],'test',status='unknown')
    def test_two_exchanges_and_explicit_industry_scope(self):
        o,s=self.inputs();v=build(o,s,{})['data'];self.assertEqual(v[0]['value'],'300')
        self.assertEqual((v[1]['up'],v[1]['down'],v[1]['flat'],v[1]['coverage'],v[1]['total']),(1,1,1,3,4))
        self.assertEqual(v[2]['value'],'0');self.assertEqual(v[1]['status'],'unknown')
    def test_missing_wrong_date_units_do_not_form_total(self):
        for field,value in [('source_as_of',None),('source_as_of','2026-10-15T15:00:00+08:00'),('amount_unit','USD'),('amount',None),('amount','NaN'),('amount','invalid')]:
            o,s=self.inputs();o['data'][0][field]=value
            self.assertFalse(any(r['id']=='amount' for r in build(o,s,{})['data']))
    def test_funds_reject_wrong_symbol_date_and_unsafe_values(self):
        raw=dict(code='512890',date='2026-10-16',net_inflow_yuan=-100,definition='主力净额',source_url=None)
        self.assertEqual(parse_fund_answer(json.dumps(raw),'SH:512890','2026-10-16')['net_inflow_yuan'],'-100')
        for field,value in [('code','513100'),('date','2026-10-15'),('net_inflow_yuan',None),('net_inflow_yuan',True),('net_inflow_yuan','NaN'),('definition',None),('unit','万元')]:
            bad=dict(raw);bad[field]=value
            with self.assertRaises((ValueError,TypeError)):parse_fund_answer(json.dumps(bad),'SH:512890','2026-10-16')
        with self.assertRaises(ValueError):parse_fund_answer('上方有资金卡片','SH:512890','2026-10-16')


if __name__=='__main__':unittest.main()
