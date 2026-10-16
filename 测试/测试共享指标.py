import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码'))
from datetime import date,timedelta
import importlib
import unittest


def bars(n=120,flat=False):
    return [dict(time=(date(2026,1,1)+timedelta(days=i)).isoformat(),open=str(100 if flat else i+1),
        close=str(100 if flat else i+1),high=str(101 if flat else i+2),low=str(99 if flat else max(.5,i)),
        amount='10000000',amount_unit='CNY',closed=True) for i in range(n)]


class IndicatorTests(unittest.TestCase):
    def test_flat_rsi_and_macd_initialization(self):
        m=importlib.import_module('指标')
        r=m.technical_series(bars(flat=True),'2026-10-15T21:00:00+08:00')
        self.assertEqual(r['series']['rsi14'][14],50)
        self.assertIsNone(r['series']['macd_dea'][32])
        self.assertEqual(r['series']['macd_hist'][33],0)
        self.assertEqual(r['summary']['ma60']['value'],100)

    def test_linear_trend_macd_and_legacy_atr(self):
        m=importlib.import_module('指标');rows=bars(70)
        r=m.technical_series(rows,'2026-10-15T21:00:00+08:00')
        self.assertAlmostEqual(r['series']['macd_dif'][33],7)
        self.assertAlmostEqual(r['series']['macd_dea'][33],7)
        self.assertEqual(r['series']['rsi14'][-1],100)
        old=m.compute_indicators(rows,rows,'2026-10-15T21:00:00+08:00')
        self.assertEqual(old['atr14']['value'],2)
        self.assertEqual(old['rs20']['value'],0)

    def test_short_unclosed_future_bars_never_make_complete_indicator(self):
        m=importlib.import_module('指标');rows=bars(5)
        rows[-1]['closed']=False
        rows.append(dict(rows[0],time='2027-01-01'))
        r=m.technical_series(rows,'2026-10-15T21:00:00+08:00')
        self.assertEqual(r['sample_count'],4)
        self.assertIsNone(r['summary']['rsi14']['value'])
        self.assertEqual(r['summary']['rsi14']['status'],'missing')

    def test_chart_read_model_uses_same_series_and_keeps_money(self):
        m=importlib.import_module('指标')
        meta={'bars':[['2026-10-14','4.245','4.242','4.250','4.187','1578769500','6664780823']],
            'columns':['time','open','close','high','low','volume','amount'],
            'updated_at':'2026-10-15T16:00:00+08:00','adjustment':'raw','amount_unit':'CNY'}
        result=m.chart_series({'day':meta},'2026-10-15T21:00:00+08:00')['day']
        self.assertEqual(result['bars'][0][6],'6664780823')
        self.assertEqual(result['technical']['sample_count'],1)
        self.assertIsNone(result['technical']['summary']['ma5']['value'])


if __name__=='__main__':unittest.main()
