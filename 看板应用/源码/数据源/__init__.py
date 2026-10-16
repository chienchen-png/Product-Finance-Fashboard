"""有界HTTP读取：固定供应商域名，无认证转发、无动态代码执行。"""
import json
import threading
import time
from urllib.parse import urlsplit, urlencode
from urllib.request import Request, urlopen

ALLOWED = {'qt.gtimg.cn','hq.sinajs.cn','web.ifzq.gtimg.cn','ifzq.gtimg.cn',
    'api.fund.eastmoney.com','push2his.eastmoney.com','vip.stock.finance.sina.com.cn','zhibo.sina.com.cn'}
_global = threading.BoundedSemaphore(4)
_hosts = {host:threading.Lock() for host in ALLOWED}


def request(url, *, form=None, encoding='utf-8', referer=None):
    host=urlsplit(url).hostname
    if urlsplit(url).scheme!='https' or host not in ALLOWED:
        raise ValueError('非允许的数据源')
    body=urlencode(form).encode() if form is not None else None
    headers={'User-Agent':'Mozilla/5.0','Referer':referer or 'https://finance.sina.com.cn/'}
    if body is not None:headers['Content-Type']='application/x-www-form-urlencoded'
    deadline=time.monotonic()+10
    with _global, _hosts[host]:
        if time.monotonic()>=deadline:raise TimeoutError('请求排队超时')
        with urlopen(Request(url,data=body,headers=headers), timeout=max(.1,deadline-time.monotonic())) as response:
            if urlsplit(response.url).hostname not in ALLOWED:raise ValueError('非允许的跳转')
            raw=response.read(8*1024*1024+1)
            if len(raw)>8*1024*1024:raise ValueError('响应过大')
            if time.monotonic()>deadline:raise TimeoutError('请求超时')
    return raw.decode(encoding)


def get_json(url, **kwargs):
    return json.loads(request(url,**kwargs))
