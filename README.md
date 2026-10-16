# 比赛看板

Windows本机模拟投资账户与市场行情看板。按“市场 → 投研 → 账户”浏览：市场展示行情、行业、排行及统计摘要；投研阅读财经快讯及宏观分析；账户展示持仓、收益与K线。支持手动录入、JSON/CSV导入和本机智能体接口。

不读取手机账户，不提交券商买卖指令。账户以用户确认信息为准，行情独立联网更新；每位用户拥有自己的本地数据。

## 下载与首次启动

1. `git clone <仓库地址>`，或下载GitHub仓库完整内容，不能只下载EXE。
2. Windows x64下双击根目录`比赛看板.exe`，保持`_internal`同级。普通使用无需Python；华泰主源需自行配置密钥，未配置时仍可使用公开补充行情。
3. 浏览器打开`http://127.0.0.1:8765`，被占用时顺延至8775，以实际打开地址为准。
4. 首次自动同步行情；“启动联动”选择5/20分钟更新。“更新行情”只同步报价、K线及数值行情。投研页选择主题后点击“更新本主题”，单独获取华泰资料；切换页面不会生成报告。产品详情内切换“K线行情 / 产品分析”；首次点击分析且无缓存时按需生成，已有缓存直接阅读，可手动更新。

GitHub仅分发文件，不托管账户或实时网页。同一电脑的其他浏览器可打开同一地址，其他设备不能通过这个127.0.0.1地址访问。关闭全部页面约5分钟后服务退出，下次双击EXE即可。

## 第一次怎么初始化

首次自动创建100万元、零持仓账户；尚未交易可直接登记首笔成交。

**已有持仓：用一次快照开账，无须补齐历史买卖。** 网页“记录 / 导入”→“手机账户快照”→“填写表单”：

| 信息 | 填写要求 |
|---|---|
| 汇总 | 手机总资产、现金余额、持仓总市值；有港股持仓时填港币折算率（人民币/港币） |
| 持仓 | 每只产品代码、数量、持仓均价、手机现价；港股均价按港币填 |
| 时间 | 上述手机数据对应的北京时间 |
| 选填 | 今日盈亏、持仓盈亏、可卖数量；未知留空 |

交易所自动识别、名称联网补全。总资产须等于现金＋持仓市值，逐项数量×手机现价须与市值匹配。有委托冻结时，可用资金不等于现金；无法确认则先撤单，待释放冻结后对账。

预览无误后确认。以后只登记快照时间之后的新成交；收益率仍以比赛初始100万元为基准，开账前收益曲线不补造。

## 日常使用

- 成交最少四项：**代码、买卖方向、数量、实际成交价**。交易所按代码自动识别（5位港股通、6位沪深北），名称联网补全，编号按内容去重，时间默认当前北京时间（补记旧成交在“更多”里改）。仅挂单不算成交，部分成交只登记实际数量。
- 费用留空按本赛事规则推定：沪深万3、北交所万2.8、港股通0.1257%（净佣金0.013%＋印花税0.1%＋过户费0.0042%＋其他0.0085%）；实际费用可覆盖。这不是实际券商费率。
- 表单、JSON/CSV均先预览后提交。开账后再次对账，数量须与基线＋新增成交一致；不能用快照掩盖漏记成交。
- 支持沪深A股、场内基金（ETF/LOF/REITs）、北交所与港股通。港股通按港币成交、人民币入账：折算率自动带出`FX:HKDCNY`，现金按成交汇率扣收，市值按最新汇率估值，持仓均价按港币显示；港股只有前复权日线，无分钟线与成交量。不支持美股、两融、可转债、期货期权与自动公司行动记账。
- 交易时段：A股与场内基金9:15—11:30、13:00—15:00；港股通9:00—12:00、13:00—16:00（不含16:00—16:10收市竞价，T+2交收）。状态条分列两个时段，联动刷新覆盖两者并集。

运行后生成根目录`数据/`；备份它即可迁移账户。更新保留个人数据，分享和提交Git时排除它。

## 智能体接入

智能体须具备**这台电脑的文件/终端或本机HTTP访问能力**；云端聊天服务不能直接访问你的127.0.0.1。智能体负责分析与登记用户确认信息，软件不内置模型或交易决策。

推荐根目录`智能体工具.py`，Python 3.10+、仅标准库，无需MCP插件：

```powershell
python -X utf8 智能体工具.py start
python -X utf8 智能体工具.py health
python -X utf8 智能体工具.py show
python -X utf8 智能体工具.py market --section overview
python -X utf8 智能体工具.py market --section ranks --product-type etf --sort up
python -X utf8 智能体工具.py market --section sectors
python -X utf8 智能体工具.py market --section news
python -X utf8 智能体工具.py kline SH:510300
python -X utf8 智能体工具.py refresh
```

每份软件使用自己根目录的`数据`，不需要切换数据库。工具默认匹配该目录的服务；`health`的`data_root`用于核对。显式指定服务可加前置参数`--url http://127.0.0.1:8765`。`refresh`异步返回，之后重读数据时间和状态。

### 阅读与更新投研

```powershell
python -X utf8 智能体工具.py market --section summary
python -X utf8 智能体工具.py market --section fund_flows
python -X utf8 智能体工具.py research
python -X utf8 智能体工具.py research --topic product --symbol SH:512890
python -X utf8 智能体工具.py research-refresh --topic market_a
```

刷新异步返回任务，随后用research读取状态与正文。主题：market_a/overseas/capital/events/product/sector/fund；产品主题需symbol，行业需当前缓存行业id作为sector。30分钟内相同查询复用缓存；同时运行最多2项，总队列6项。失败保留旧文。行业资金文本与产品资金快照均为**供应商生成、待核验**；不作为已确认交易依据。

### 登记确认成交

把用户确认信息写入临时JSON。以下仅示格式，代码保留前导零，价格、数量、时间须替换为真实成交：

```json
{"kind":"trades","rows":[{"code":"510300","side":"buy","quantity":100,"price":"4.216","time":"2026-10-16T14:00:00+08:00"}]}
```

```powershell
python -X utf8 智能体工具.py preview --input 本次成交.json --ticket 本次.预览.json
python -X utf8 智能体工具.py commit --ticket 本次.预览.json
```

客户端补交易所和名称，不补成交价、时间、数量。预览返回变更与版本，不改账；仅用户已确认的实际成交可提交。票据5分钟有效，过期或版本冲突须重读并重新预览。票据不提交Git。

### 快照、自选与当前委托

同样走preview→commit。`kind`支持`trades`、`snapshot`、`watchlist`、`pending`；后两者是**替换完整当前列表**，不是追加。

快照格式示例，全部数值与时间须改为手机实况：

```json
{"kind":"snapshot","snapshot":{"id":"自定义唯一快照编号","reported_at":"2026-10-16T13:30:00+08:00","summary":{"total_assets":"1000000","available_cash":"996000","market_value":"4000","daily_profit":null,"unrealized_profit":null},"positions":[{"code":"510300","quantity":1000,"average_cost":"4","price":"4"}]}}
```

`available_cash`在无冻结时表达现金余额。快照价格与均价来自手机，不能用接口现价替代。空仓`positions`传`[]`。含港股持仓时在`snapshot`一级加`"fx":"人民币/港币折算率"`，港股均价按港币填；不填则用已缓存汇率，均无则拒绝入账。自选格式：`{"kind":"watchlist","rows":[{"symbol":"SH:510300","name":"沪深300ETF","product_type":"etf"}]}`。委托字段见源码`账户台账.py`的`validate_pending`，委托不增加真实持仓。

### 直接调用HTTP

先`GET /health`核对`data_root`；再`GET /`，从页面`localToken='...'`取得本次会话令牌。其他接口带`X-Dashboard-Token`，POST还须`Content-Type: application/json`。令牌不上传、不提交Git，重启后重新读取。

| 接口 | 用途 / 参数 |
|---|---|
| `GET /api/view` | 账户汇总、持仓、收益观察和数据时间 |
| `GET /api/state?client=local-agent` | 联动及采集状态 |
| `GET /api/market?section=overview` | 指数和跟踪产品报价 |
| `GET /api/market?section=sectors&group=industry` | 行业强弱 |
| `GET /api/market?section=ranks&product_type=etf&sort=up` | stock/etf/lof；up/down/amount/turnover |
| `GET /api/market?section=news` | 快讯 |
| `GET /api/market?section=nav&symbol=SH:510300` | 已采集的披露净值，非实时IOPV |
| `GET /api/research` | 报告目录与任务状态；topic/symbol/sector选取正文 |
| `POST /api/research/refresh` | 受控主题更新，例如`{"topic":"product","symbol":"SH:512890"}` |
| `GET /api/lookup?symbol=SH:510300` | 名称及报价 |
| `GET /api/kline?symbol=SH:510300&period=day&adjustment=raw` | K线与指标；day/m5、raw/qfq按实际支持 |
| `POST /api/control` | `{"action":"refresh","client":"local-agent","interval":5}`；action也可start/stop，interval为5或20分钟 |
| `POST /api/import/preview` | 导入对象；返回`token`与`revision`，有效5分钟 |
| `POST /api/import/commit` | `{"token":"预览token","expected_revision":"预览revision"}` |

原始HTTP导入成交/持仓的`exchange`（SH/SZ/BJ/HK）可由`code`推导、`name`可留空由接口补；港股成交与委托需带`fx`（人民币/港币折算率），缺折算率拒绝入账。400为字段错误、403为本机会话/来源校验失败、409为版本冲突，均不可视为成功。K线看`status`、`pending`、`message`、`data`，失败不持续等待。本机API不提供买卖下单。

### 一句话交给智能体

上传后把`<仓库地址>`换成真实GitHub地址：

> 请把比赛看板从 <仓库地址> 克隆到本机独立文件夹，先读README和AGENTS.md；Windows下启动比赛看板.exe，核对health数据目录并读取账户。需要智能体工具时检查Python 3.10+；检查本机是否配置自己的HT_APIKEY，已配置则华泰报价优先、公开源补充，未配置先用补充源并指导本机配置，不把密钥上传。我若已有持仓，一次收集手机总资产、现金、市值、快照时间和各持仓代码/数量/均价/现价，以snapshot预览并登记开账，此后仅登记我确认的新成交。用market/kline及market --section huatai读取共享行情和研究资料，投研用research读取、research-refresh按需更新；先核时间、口径与证据，再分析；写入走preview→commit，不改源码或派生缓存。

## 行情来源、指标与配置

**已配置HT_APIKEY时，已验证可用的报价字段优先使用华泰Skill；其他能力按实际覆盖使用现有补充源。** 华泰适配器按官方脚本的只读HTTP协议内置，EXE无需另外运行Skill脚本。当前具体覆盖见`看板应用/规划/接口说明.md`。

| 数据 | 来源 | 配置 |
|---|---|---|
| 股票/ETF/LOF/REITs等报价 | 华泰Skill getQuote优先；腾讯/新浪补充及回退 | 华泰需HT_APIKEY；无密钥仍可使用公开源 |
| 港股通报价与日线 | 腾讯（华泰未覆盖港股） | 联网即可；仅前复权日线，无成交量与分钟线 |
| 港元/人民币折算率 | 新浪外汇`fx_shkdcny` | 联网即可；缺失时回退最近一笔港股成交汇率 |
| 沪深及部分港美指数K线 | 腾讯 | 联网即可 |
| 北交所K线、境内日K成交额、披露净值 | 东方财富 | 联网即可，部分接口可能失败 |
| 行业、股票/ETF/LOF排行、快讯 | 新浪 | 联网即可 |
| MA5/10/20/60、MACD、RSI14、ATR14、收益/波动等 | 本机`指标.py`计算 | 样本足够才返回，缺失不填造 |
| 华泰市场/海外/资金/政策/行业/产品分析 | marketInsight / diagnosisStock原文 | 配置HT_APIKEY，投研页按主题更新 |
| 三只已验收ETF主力净流入快照 | queryIndicator严格JSON校验 | 投研页“资金观察 → 更新持仓资金”；校验失败不展示 |

K线返回`technical`（指标序列和摘要）与`indicators`，具体口径及样本要求以源码为准。`指标.py`另提供组合协方差等纯计算函数；不声称提供完整因子库、选股回测或自动投资。产品资金快照标为供应商报告值；不代表ETF申赎净流入，也不代表可验证的全市场资金流。行业资金仅作文本观察；概念与公告未启用。

公开网页接口并非稳定授权行情服务，可能延迟、缺字段或不可访问；未知来源时间不冒充实时。无数据/权限受限模块隐藏，K线失败显示原因；缓存最多50个产品，有旧缓存先出图，等待上限30秒。行情查询只发送产品参数，不发送账户资产、成交价或持仓数量。

在Windows“用户环境变量”中设置自己的`HT_APIKEY`，完全退出服务后重启；也可使用用户目录`.htsc-skills/config`中的`HT_APIKEY=自己的密钥`。认证不进入项目或Git。可设置`HTSC_MARKET_MODE=public`显式只用补充源。

getQuote不返回行情时间，显示时间待核；`reference_quote`保留补充源时点但不冒充华泰时点，`source_fields`标明量额等字段来源。K线连续数组尚未由华泰稳定取得，继续使用原接口。

投研页保留缓存目录，空主题显示暂无资料；保留供应商AI原文与内容哈希，日期、事件、指标口径待独立核验，不自动变成交易信号；失败保留旧文和原取数时间。AI可用`market --section huatai`读取与网页相同的缓存。报告独立存入`数据/投研缓存.json`，与行情分开刷新。默认模拟组不等于手机比赛账户。

## 源码与维护

```text
比赛看板.exe / _internal/  程序及运行库
README.md / AGENTS.md      人与智能体入口
智能体工具.py              本机API客户端
看板应用/源码/             服务、账务、页面、指标、行情适配器
看板应用/资源/             日历及版本清单
看板应用/测试/             临时账户及浏览器回归
看板应用/构建/             构建和仓库准备工具
数据/                      首次运行生成，Git忽略
```

开发建议Python 3.14（本版验收版本）；EXE用户无需执行：

```powershell
python -m pip install -r requirements-dev.txt
python -X utf8 看板应用/源码/启动器.py
python -X utf8 看板应用/测试/运行全部测试.py
powershell -NoProfile -ExecutionPolicy Bypass -File 看板应用/构建/构建发布.ps1 -目标 独立
```

浏览器测试需本机Edge，个别构建测试需PowerShell 7（pwsh）。源码启动与根目录EXE读取同一份本机数据。构建前关闭对应程序：独立仓库必须显式传`-目标 独立`，只更新仓库根程序；作者本机默认`-目标 本机`，只更新`看板应用`，不会自动同步开源目录。两种构建均保留数据。不生成压缩包。

上传时以**本目录为仓库根**，提交源码及运行文件；检查`git status`，排除`数据/`、临时成交/快照文件与票据。代码采用MIT许可，图表与依赖保留各自许可。迁移备份整个`数据/`；故障看`数据/看板服务.log`，不要修改`_internal`。
