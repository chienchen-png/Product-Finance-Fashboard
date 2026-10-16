"""本机资料路由：认证、ETag、主题白名单、后台提交与账户隔离。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码'))
import json
import tempfile
import threading
import unittest
from unittest.mock import patch,Mock
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import 账户台账 as ledger
import 投研缓存 as research
from 看板服务 import create_server


class ResearchApiTests(unittest.TestCase):
    def test_routes_are_authenticated_bounded_and_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'账户记录/比赛账户.json';ledger.init(p)
            server=create_server(p,0,runner=lambda _:{});thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}';before=p.read_bytes()
            def request(route,body=None,headers=None):
                h={'X-Dashboard-Token':server.local_token,'Content-Type':'application/json','Origin':base};h.update(headers or {})
                return urlopen(Request(base+route,data=json.dumps(body).encode() if body is not None else None,headers=h),timeout=3)
            try:
                with request('/api/research') as r:etag=r.headers['ETag'];self.assertEqual(json.load(r)['documents'],[])
                with self.assertRaises(HTTPError) as e:request('/api/research',headers={'If-None-Match':etag})
                self.assertEqual(e.exception.code,304);e.exception.close()
                with self.assertRaises(HTTPError) as e:request('/api/research',headers={'X-Dashboard-Token':''})
                self.assertEqual(e.exception.code,403);e.exception.close()
                engine=Mock();engine.submit.return_value={'state':'queued','key':'market_a:market'}
                with patch.object(research,'engine',return_value=engine):
                    with request('/api/research/refresh',{'topic':'market_a'}) as r:self.assertEqual(r.status,202)
                    engine.submit.assert_called_once_with('market_a',None,None)
                    for body in ({'topic':'market_a','tool':'buy'},[],{'topic':'x','query':'free'}):
                        with self.assertRaises(HTTPError) as e:request('/api/research/refresh',body)
                        self.assertEqual(e.exception.code,400);e.exception.close()
                    self.assertEqual(engine.submit.call_count,1)
                with self.assertRaises(HTTPError) as e:request('/api/research?topic=buy')
                self.assertEqual(e.exception.code,400);e.exception.close()
                self.assertEqual(p.read_bytes(),before)
            finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
