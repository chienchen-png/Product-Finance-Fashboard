"""只读华泰接口验收：校验官方脚本，保存响应与耗时，不查询账户、不交易。"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import 环境检查 as env
import 账户核心 as core


def cases(group):
    rows=[]
    if group in ('all','quotes'):
        for symbol in ('SH:512890','SH:513100','SH:518880','SZ:159920','SZ:161725','SH:508000',
                       'SH:601688','SH:000001','SZ:399001','SZ:399006','BJ:920690'):
            market,code=symbol.split(':')
            rows.append(dict(id='quote_'+market+code,skill='a-share-paper-trading',tool='getQuote',
                args=['--stock-code',code,'--exchange',market],symbol=symbol))
    if group in ('all','research'):
        for name,skill,tool,query in (
            ('daily','query-indicator','queryIndicator','查询红利低波ETF华泰柏瑞512890最近一个月逐交易日的日K线，列出每个交易日日期、开盘价、最高价、最低价、收盘价、成交量及成交额。'),
            ('minute','query-indicator','queryIndicator','查询纳指ETF国泰513100最近一个交易日逐根5分钟K线，列出时间、开盘价、最高价、最低价、收盘价、成交量和成交额。'),
            ('cross_market','query-indicator','queryIndicator','查询红利低波ETF华泰柏瑞512890、纳指ETF国泰513100、黄金ETF华安518880、恒生指数、恒生科技指数、纳斯达克100指数和标普500指数的最新价、涨跌幅、行情日期和时间。'),
            ('flows','query-indicator','queryIndicator','查询当前A股各行业板块的涨跌幅、主力资金净流入、成交额和排行，注明行情日期、时间及资金流口径。'),
            ('indicators','query-indicator','queryIndicator','查询红利低波ETF华泰柏瑞512890的MA5、MA20、MA60、MACD、KDJ、RSI、今日及近3日和近5日主力净流入，并注明指标日期与口径。'),
            ('events','financial-analysis','marketInsight','整理最近24小时影响纳指ETF国泰513100、黄金ETF华安518880和红利低波ETF华泰柏瑞512890的市场新闻、政策和事件，列出原始来源与发布时间，区分事实与观点。'),
            ('screen','select-stock','selectStock','当前成交额最高的5只场内ETF，列出代码、名称、交易所、涨跌幅、成交额及行情日期。')):
            rows.append(dict(id=name,skill=skill,tool=tool,args=['--query',query],query=query))
    if group=='depth':
        for name,query in (
            ('daily_text','请用纯文本表格返回512890最近5个交易日每天的日期、开盘价、最高价、最低价、收盘价、成交量和成交额，不要引用卡片，无法返回明细请明确说明。'),
            ('minute_text','请用纯文本表格返回513100最近一个交易日最后6根5分钟K线的时间、开盘价、最高价、最低价、收盘价、成交量和成交额，不要引用卡片，无法返回明细请明确说明。'),
            ('flows_top5','查询最新A股行业主力资金净流入前5名，返回行业名称、主力净流入金额、涨跌幅、行情日期、数据来源和资金流定义。')):
            rows.append(dict(id=name,skill='query-indicator',tool='queryIndicator',args=['--query',query],query=query))
    return rows


def probe(case):
    start=time.monotonic();item=next(x for x in env.manifest()['技能包'] if x['名称']==case['skill'])
    folder=env.skill_folder(case['skill'])
    if not folder or not env.verify(folder,item['文件'])[0]:raise ValueError('官方脚本缺失或哈希不一致')
    script=next(folder/name for name in item['文件'] if name.endswith('.py'))
    try:
        call=subprocess.run([sys.executable,str(script),case['tool'],*case['args']],
            env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8'),capture_output=True,
            text=True,encoding='utf-8',timeout=100)
        response=json.loads(call.stdout)
    except subprocess.TimeoutExpired:
        response={'ok':False,'error':{'category':'timeout','message':'100秒验收上限，未取得完整响应'}}
    except (OSError,ValueError) as exc:
        response={'ok':False,'error':{'category':'local','message':type(exc).__name__}}
    clean=re.sub(r'ht_[A-Za-z0-9]{24,}','[REDACTED]',json.dumps(response,ensure_ascii=False))
    response=json.loads(clean)
    data=response.get('data');answer=(data or {}).get('answer') or (data or {}).get('result') if isinstance(data,dict) else None
    return dict(case,checked_at=core.now(),elapsed_seconds=round(time.monotonic()-start,3),
        script_sha256=env.digest(script),response=response,data_keys=list(data) if isinstance(data,dict) else [],
        answer_characters=len(answer) if isinstance(answer,str) else None)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group',choices=['all','quotes','research','depth'],default='all')
    parser.add_argument('--output',type=Path,default=Path('投研/当前/运行/华泰接口验收.json'))
    args=parser.parse_args()
    result={'tested_at':core.now(),'method':'官方脚本哈希校验后只读调用；查询为程序能力验收样例','cases':[]}
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs=[pool.submit(probe,c) for c in cases(args.group)]
        for future in as_completed(jobs):
            row=future.result();result['cases'].append(row)
            core.atomic_text(args.output,json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps({k:row.get(k) for k in ('id','elapsed_seconds','data_keys','answer_characters')}|
                {'ok':row['response'].get('ok'),'error':row['response'].get('error')},ensure_ascii=False),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
