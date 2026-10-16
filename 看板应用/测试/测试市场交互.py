"""本机浏览器验收；外网拦截，仅使用临时账户与确定数据。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码'))
import tempfile
import threading
import unittest
import 账户核心 as core
import 账户台账 as ledger
import 市场同步 as market
from 数据契约 import dataset
from 看板服务 import create_server


class MarketBrowserTests(unittest.TestCase):
    def test_unavailable_products_stop_loading_and_empty_modules_hide(self):
        from playwright.sync_api import sync_playwright
        from urllib.error import HTTPError
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'账户记录/比赛账户.json';ledger.init(p)
            engine=market.collector(p)
            def denied():raise HTTPError('https://example.invalid',403,'Forbidden',None,None)
            def offline():raise ConnectionError('offline')
            engine.update_section('sectors:industry',lambda:dataset('sectors',[dict(name='旧板块',change_pct='.01',amount='1')],'test'),True)
            engine.update_section('sectors:industry',denied,True)
            for symbol,fetch in [('INDEX:NDX',denied),('SH:600010',denied),('SH:600011',offline)]:
                engine.update_section('kline:'+symbol+':day:raw',fetch,True)
            market._store_section(p,'overview',dataset('overview',[
                dict(symbol='FX:USDCNY',name='无K线来源',price='7',product_type='fx'),
                dict(symbol='INDEX:NDX',name='无权限指数',price='20000',product_type='index')],'test'))
            market._store_section(p,'ranks:stock:up',dataset('ranks',[
                dict(symbol='SH:600010',name='权限受限产品',price='4'),
                dict(symbol='SH:600011',name='网络失败产品',price='4'),
                dict(symbol='SH:600012',name='待补数产品',price='4')],'test'))
            server=create_server(p,0,runner=lambda _:{});thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with sync_playwright() as driver:
                    browser=driver.chromium.launch(channel='msedge',headless=True);page=browser.new_page()
                    page.route('**/*',lambda r:r.continue_() if r.request.url.startswith('http://127.0.0.1:') else r.abort())
                    page.goto(f'http://127.0.0.1:{server.server_port}/');page.locator('[data-page="market"]').click()
                    page.wait_for_selector('#rank-rows [data-product="SH:600010"]')
                    self.assertFalse(page.locator('#index-strip').is_visible())
                    self.assertFalse(page.locator('#sector-panel').is_visible())
                    self.assertFalse(page.locator('#news-panel').is_visible())
                    page.locator('#rank-rows [data-product="SH:600010"]').click()
                    page.wait_for_function("document.getElementById('kb-market').textContent.includes('权限受限')")
                    self.assertFalse(page.locator('#k-market').is_visible())
                    self.assertEqual(page.locator('#kb-market .kbtn').count(),0)
                    self.assertFalse(any('SH:600010' in k for k in engine._requests))
                    page.locator('#product-close').click()
                    page.locator('#rank-rows [data-product="SH:600011"]').click()
                    page.wait_for_function("document.getElementById('kb-market').textContent.includes('连接失败')")
                    self.assertNotIn('权限',page.locator('#kb-market').inner_text())
                    page.locator('#product-close').click()
                    page.locator('#rank-rows [data-product="SH:600012"]').click()
                    page.wait_for_function("document.getElementById('kb-market').textContent.includes('正在获取')")
                    page.evaluate("klinePendingSince.set('SH:600012:day',Date.now()-31000)")
                    page.evaluate("activateDetail(MarketDashboard.currentProduct('SH:600012'),'market')")
                    page.wait_for_function("document.getElementById('kb-market').textContent.includes('获取超时')")
                    self.assertFalse(page.locator('#k-market').is_visible())
                    # 即使账户/市场轮询没有新版本，等待上限仍由独立计时器执行。
                    page.clock.install()
                    page.evaluate("""() => {
                      const bar=document.createElement('div');bar.id='kb-timer';bar.dataset.symbol='SH:600013';
                      const plot=document.createElement('div');plot.id='k-timer';document.body.append(bar,plot);
                      klineStates.set('SH:600013:day',{pending:true,message:'正在获取K线…'});
                      showKlineMessage(bar,'timer','SH:600013','day');
                    }""")
                    page.clock.fast_forward(31000)
                    self.assertIn('获取超时',page.locator('#kb-timer').inner_text())
                    browser.close()
            finally:server.shutdown();server.server_close();thread.join()

    def test_tabs_market_charts_tooltips_and_mobile(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'账户记录/比赛账户.json';ledger.init(p)
            now=core.now()
            fixtures={
                'overview':dataset('overview',[dict(symbol='INDEX:NDX',name='纳斯达克100',product_type='index',price='29950.82',change_pct='-.0202',source_as_of=None,source_local_time='2026-10-14 17:15:59')],'test'),
                'ranks:stock:up':dataset('ranks',[dict(symbol='SH:510300',name='测试产品',price='4.242',change_pct='.01',amount='100000000',turnover_rate='.02')],'test'),
                'sectors:industry':dataset('sectors',[dict(id='BK1',name='测试板块',amount='100000000',change_pct='.03',member_count=19,main_net=None)],'test',source_as_of=now),
                'flows':dataset('flows',[dict(time=now,main_net='20000000')],'test',source_as_of=now),
                'news':dataset('news',[dict(id='n',title='<script>不能执行</script>',source='测试来源',published_at=now,url='https://finance.sina.com.cn/')],'test',source_as_of=now)}
            # 使用实际数据量，防止单行样本掩盖网格拉伸与滚动问题。
            fixtures['overview']['data'] += [dict(fixtures['overview']['data'][0],symbol=f'SH:{600100+i}',name=f'指数{i}') for i in range(13)]
            fixtures['ranks:stock:up']['data'] += [dict(fixtures['ranks:stock:up']['data'][0],symbol=f'SH:{600000+i}',name=f'排行产品{i}') for i in range(19)]
            fixtures['sectors:industry']['data'] += [dict(fixtures['sectors:industry']['data'][0],id=f'BK{i}',name=f'行业{i}',change_pct=str((i-24)/500),amount=str(10000000+i*1000000)) for i in range(1,49)]
            fixtures['sectors:industry']['data'][-1]['change_pct']=None
            fixtures['news']['data'] += [dict(fixtures['news']['data'][0],id=f'n{i}',title=f'市场快讯{i}') for i in range(99)]
            for k,v in fixtures.items():market._store_section(p,k,v)
            cache=core.load_cache(p)
            cache['series']={'SH:510300':{'name':'测试产品','day':dict(bars=[['2026-10-14','4.2','4.242','4.3','4.1','100','424']],columns=['time','open','close','high','low','volume','amount'],adjustment='raw',volume_unit='shares',amount_unit='CNY')}}
            core.save_cache(p,cache)
            server=create_server(p,0,runner=lambda _:{});thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with sync_playwright() as engine:
                    browser=engine.chromium.launch(channel='msedge',headless=True)
                    page=browser.new_page(viewport={'width':1440,'height':1100})
                    page.route('**/*',lambda route:route.continue_() if route.request.url.startswith('http://127.0.0.1:') else route.abort())
                    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/')
                    page.wait_for_function("document.getElementById('cash').textContent!=='—'")
                    account_main=page.locator('main').bounding_box()
                    page.locator('[data-page="market"]').click()
                    page.wait_for_selector('#index-strip .index-card')
                    self.assertEqual(account_main['x'],page.locator('main').bounding_box()['x'])
                    self.assertEqual(account_main['width'],page.locator('main').bounding_box()['width'])
                    self.assertEqual(page.locator('#rank-panel thead th').count(),4)
                    self.assertGreater(page.locator('#sector-panel').bounding_box()['width'],page.locator('#rank-panel').bounding_box()['width']*1.5)
                    self.assertIn('纳斯达克100',page.locator('#index-strip').inner_text())
                    self.assertEqual(page.locator('#flow-chart').count(),0)
                    self.assertEqual(page.locator('#sector-type option[value="concept"]').count(),0)
                    page.wait_for_function("document.getElementById('sector-rows').textContent.includes('测试板块')")
                    map_height=page.locator('#sector-panel').bounding_box()['height']
                    self.assertAlmostEqual(map_height,page.locator('#rank-panel').bounding_box()['height'],delta=2)
                    self.assertTrue(page.evaluate("document.getElementById('rank-scroll').scrollHeight>document.getElementById('rank-scroll').clientHeight"))
                    self.assertLess(page.locator('#index-strip').bounding_box()['height'],400)
                    self.assertEqual(page.evaluate("echarts.getInstanceByDom(document.getElementById('sector-map')).getOption().series[0].left"),0)
                    heat=page.evaluate("echarts.getInstanceByDom(document.getElementById('sector-map')).getOption().series[0].data")
                    self.assertNotEqual(heat[0]['itemStyle']['color'],heat[24]['itemStyle']['color'])
                    self.assertEqual(heat[-1]['itemStyle']['color'],'#dce3e6')
                    page.locator('#sector-map').scroll_into_view_if_needed()
                    box=page.locator('#sector-map').bounding_box()
                    page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2)
                    page.wait_for_function("document.getElementById('sector-map').textContent.includes('成分数量')")
                    page.evaluate("document.getElementById('rank-scroll').scrollTop=150;document.getElementById('news-list').scrollTop=120")
                    # 即使真实数据变化导致重绘，保留读者的位置。
                    fixtures['ranks:stock:up']['data'][1]['price']='4.25'
                    fixtures['news']['data'][1]['title']='更新后的市场快讯'
                    market._store_section(p,'ranks:stock:up',fixtures['ranks:stock:up'])
                    market._store_section(p,'news',fixtures['news'])
                    page.evaluate("MarketDashboard.update()")
                    page.wait_for_function("document.getElementById('news-list').textContent.includes('更新后的市场快讯')")
                    self.assertEqual(page.evaluate("document.getElementById('rank-scroll').scrollTop"),150)
                    self.assertEqual(page.evaluate("document.getElementById('news-list').scrollTop"),120)
                    page.locator('#sector-view').select_option('table')
                    page.wait_for_selector('#sector-table',state='visible')
                    self.assertAlmostEqual(map_height,page.locator('#sector-panel').bounding_box()['height'],delta=1)
                    self.assertFalse(page.locator('#sector-legend').is_visible())
                    self.assertIn('3.00%',page.locator('#sector-rows').inner_text())
                    page.locator('#sector-view').select_option('map')
                    page.wait_for_selector('#sector-map',state='visible')
                    # 容器变化而非窗口变化时也应重新调整图表。
                    page.locator('#sector-panel').evaluate("el=>el.style.width='85%'")
                    page.wait_for_function("Math.abs(echarts.getInstanceByDom(document.getElementById('sector-map')).getWidth()-document.getElementById('sector-map').clientWidth)<2")
                    page.locator('#sector-panel').evaluate("el=>el.style.width=''")
                    for width,columns in [(1920,2),(1440,2),(1000,1),(768,1),(390,1)]:
                        page.set_viewport_size({'width':width,'height':1100})
                        page.wait_for_function("Math.abs(echarts.getInstanceByDom(document.getElementById('sector-map')).getWidth()-document.getElementById('sector-map').clientWidth)<2")
                        self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('.market-grid')).gridTemplateColumns.split(' ').length"),columns)
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                        # 指数区最后一行同样铺满，避免超宽屏出现一长条空白。
                        cards=page.locator('#index-strip .index-card')
                        self.assertAlmostEqual(cards.last.bounding_box()['x']+cards.last.bounding_box()['width'],page.locator('#index-strip').bounding_box()['x']+page.locator('#index-strip').bounding_box()['width'],delta=2)
                    page.set_viewport_size({'width':1440,'height':1100})
                    self.assertEqual(page.locator('#news-list script').count(),0)
                    self.assertIn('<script>',page.locator('#news-list').inner_text())
                    page.locator('#rank-rows tr').first.click()
                    page.wait_for_function("document.getElementById('kb-market').textContent.includes('日线')")
                    # 无数据的周期不显示按钮；打开产品会自动补数，取到数据后才出现按钮。
                    self.assertEqual(page.locator('#kb-market .kbtn[data-v="m5"]').count(),0)
                    wanted={'kline:SH:510300:m5:raw','kline:SH:510300:day:qfq'}
                    for _ in range(50):
                        if wanted<=set(market.collector(p)._requests):break
                        page.wait_for_timeout(100)
                    self.assertTrue(wanted<=set(market.collector(p)._requests),market.collector(p)._requests)
                    self.assertEqual(page.locator('#kb-market .kbtn[data-v="day"]').count(),1)
                    cache=core.load_cache(p)
                    cache['series']['SH:510300']['m5']=dict(cache['series']['SH:510300']['day'],bars=[['2026-10-15 10:00','4.2','4.333','4.4','4.1','100','433']])
                    core.save_cache(p,cache)
                    page.wait_for_selector('#kb-market .kbtn[data-v="m5"]',timeout=20000)
                    page.locator('#kb-market .kbtn[data-v="m5"]').click()
                    page.wait_for_function("echarts.getInstanceByDom(document.getElementById('k-market'))?.getOption().series[0].data[0][1]===4.333",timeout=10000)
                    page.evaluate('applyData({...d})')
                    self.assertTrue(page.evaluate("!!echarts.getInstanceByDom(document.getElementById('k-market'))"))
                    self.assertIn('MA60',page.evaluate("echarts.getInstanceByDom(document.getElementById('k-market')).getOption().legend[0].data"))
                    page.locator('#product-close').click()
                    # 同一产品重开立即复用内存缓存；期间不重读K线API，更不等待外部接口。
                    reads=[];page.on('request',lambda r:reads.append(r.url) if '/api/kline?' in r.url else None)
                    page.locator('#rank-rows tr').first.click()
                    page.wait_for_selector('#k-market canvas')
                    self.assertEqual(reads,[])
                    page.locator('#product-close').click()
                    page.set_viewport_size({'width':390,'height':844})
                    page.wait_for_function('document.documentElement.scrollWidth<=390')
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390)
                    page.locator('[data-page="account"]').click()
                    self.assertTrue(page.locator('#account-page').is_visible())
                    self.assertFalse(errors,errors)
                    browser.close()
            finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
