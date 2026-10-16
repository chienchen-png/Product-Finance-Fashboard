"""独立客户端通过本机API预览/提交；全程临时账户、断开外部行情。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'源码'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'构建'))
from contextlib import redirect_stdout
import io
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
import 账户台账 as ledger
import 账户核心 as core
from 看板服务 import create_server
import 智能体工具 as agent


class AgentTests(unittest.TestCase):
    def test_only_loopback_addresses_are_accepted(self):
        for url in ('https://example.com', 'http://localhost:8765', 'http://127.0.0.1:8765/remote', 'http://user@127.0.0.1:8765'):
            with self.assertRaises(ValueError):agent.Client(url)

    def test_minimum_fill_snapshot_version_conflict_and_account_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'账户记录/比赛账户.json';ledger.init(path)
            server=create_server(path,0,runner=lambda _:{});thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            url=f'http://127.0.0.1:{server.server_port}'
            def run(*args):
                out=io.StringIO()
                with redirect_stdout(out):self.assertEqual(agent.main(['--url',url,*map(str,args)]),0)
                return json.loads(out.getvalue())
            try:
                before=path.read_bytes()
                with patch('数据源.公共行情.fetch_quotes',return_value={}):
                    client=agent.Client(url)
                    # 不靠网络或账户事实填成交价；名称失败仅回退代码。
                    enriched=agent.enrich(client,{'kind':'trades','rows':[dict(code='510300',side='buy',quantity=100,price='4',time=core.now())]})
                    self.assertEqual(enriched['rows'][0]['exchange'],'SH')
                    self.assertEqual(path.read_bytes(),before)
                    snapshot={'kind':'snapshot','snapshot':{'id':'init','reported_at':core.now(),'summary':dict(total_assets='1000000',market_value='4000',available_cash='996000'), 'positions':[dict(code='510300',quantity=1000,average_cost='4',price='4')]}}
                    payload=Path(folder)/'本次快照.json';payload.write_text(json.dumps(snapshot),encoding='utf-8')
                    ticket=Path(folder)/'本次.预览.json'
                    preview=run('preview','--input',payload,'--ticket',ticket)
                    self.assertNotIn('token',preview)
                    self.assertEqual(path.read_bytes(),before)
                    run('commit','--ticket',ticket)
                    self.assertEqual(run('show')['summary']['positions'][0]['quantity'],1000)
                    row=dict(code='510300',side='buy',quantity=100,price='4',time=core.now())
                    payload.write_text(json.dumps({'kind':'trades','rows':[row]}),encoding='utf-8')
                    run('preview','--input',payload,'--ticket',ticket)
                    run('commit','--ticket',ticket)
                    self.assertEqual(run('show')['summary']['positions'][0]['quantity'],1100)
                    run('commit','--ticket',ticket)  # 相同票据重复提交幂等。
                    self.assertEqual(run('show')['summary']['positions'][0]['quantity'],1100)
                    run('preview','--input',payload,'--ticket',ticket)
                    account=core.load_account(path);account['initial_cash']='1000001.00';core.save_account(path,account)
                    with self.assertRaisesRegex(ValueError,'409'):run('commit','--ticket',ticket)
                self.assertEqual(run('health')['data_root'],str(__import__('路径').数据根()))
                self.assertEqual(client.request('/api/kline?symbol=FX:USDCNY')['status'],'unsupported')
            finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
