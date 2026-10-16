"""仅启用已重复取数验证的披露净值；不含失败的板块、资金及K线端点。"""
from urllib.parse import urlencode
from 数据契约 import dataset, decimal_text as num, validate_symbol
from . import get_json


def fetch(kind, params):
    if kind!='nav':
        raise ValueError('此来源仅启用披露净值')
    symbol=validate_symbol(params['symbol'])
    market,code=symbol.split(':')
    if market not in ('SH','SZ'):raise ValueError('此类净值未验证')
    args=dict(fundCode=code,pageIndex=1,pageSize=30)
    raw=get_json('https://api.fund.eastmoney.com/f10/lsjz?'+urlencode(args),referer='https://fundf10.eastmoney.com/')
    source=(raw.get('Data') or {}).get('LSJZList') or []
    rows=[dict(symbol=symbol,date=v['FSRQ'],unit_nav=num(v['DWJZ']),cumulative_nav=num(v.get('LJJZ')),
        currency='CNY',basis='最新披露净值；不是实时IOPV') for v in source]
    if not rows:raise ValueError('无披露净值')
    return dataset('nav',rows,'东方财富基金净值',source_as_of=rows[0]['date']+'T00:00:00+08:00',
        source_time_kind='disclosure_date',symbol=symbol)
