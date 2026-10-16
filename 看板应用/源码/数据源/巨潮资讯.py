"""公告必须按证券代码及orgId匹配；关键词全文命中不算产品公告。"""
from datetime import datetime, timedelta
from 数据契约 import TZ, dataset, validate_symbol
from . import get_json
from .公共行情 import clean_text


def fetch(kind, params):
    if kind!='announcements':raise ValueError('不支持的数据类型')
    symbol=validate_symbol(params['symbol']);market,code=symbol.split(':')
    if market not in ('SH','SZ','BJ'):raise ValueError('公告市场未验证')
    found=get_json('https://www.cninfo.com.cn/new/information/topSearch/query',form={'keyWord':code,'maxNum':5})
    if not isinstance(found,list):raise ValueError('公告证券解析失败')
    match=next((r for r in found if r.get('code')==code and r.get('orgId')),None)
    if not match:raise ValueError('该产品公告覆盖未验证')
    now=datetime.now(TZ)
    args=dict(pageNum=1,pageSize=20,column='sse' if market=='SH' else 'szse' if market=='SZ' else 'bse',
        tabName='fulltext',plate='',stock=code+','+match['orgId'],searchkey='',secid='',category='',trade='',
        seDate=(now-timedelta(days=30)).date().isoformat()+'~'+(now+timedelta(days=1)).date().isoformat(),
        sortName='time',sortType='desc',isHLtitle='true')
    raw=get_json('https://www.cninfo.com.cn/new/hisAnnouncement/query',form=args)
    rows=[]
    for item in (raw.get('announcements') or [])[:20]:
        if item.get('secCode')!=code or item.get('orgId')!=match['orgId']:continue
        day=datetime.fromtimestamp(item['announcementTime']/1000,TZ).date().isoformat()
        attachment=str(item.get('adjunctUrl',''))
        if not attachment.startswith('finalpage/') or '..' in attachment:continue
        rows.append(dict(id=str(item['announcementId']),title=clean_text(item['announcementTitle']),summary='',
            source='巨潮资讯',url='https://static.cninfo.com.cn/'+attachment,published_at=None,
            announcement_date=day,date_precision='day',retrieved_at=now.isoformat(timespec='seconds'),
            symbols=[symbol],association_type='exact_security'))
    return dataset('announcements',rows,'巨潮资讯',status='unknown',reason='披露日期可用，首次发布时间未知',
        coverage={'symbol':symbol,'returned':len(rows),'complete':False})
