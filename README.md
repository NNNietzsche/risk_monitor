# 资产风险监控页面

新增 FlightRadarAPI 和本地 MarineTrafficAPI 实验接入，默认每 30 分钟采集，船舶/航空分别手动刷新。接入边界、样例和 SDK 升级方式见 [SDK 接入说明](docs/sdk-integration.md)，服务器访问与运维见 [测试部署](docs/server-test.md)。

本系统独立运行，导航只保留资产监控内容。真实数据源为 Flightradar24（FlightRadarAPI）与 MarineTraffic API；通过“添加监控对象”接入。旧 Digitraffic、ADSB.lol 适配器及候选发现入口已移除，历史数据保留。模拟源仅用于明确标识的演示与规则验证。

Python / FastAPI 同时提供页面和 API，SQLite 保存记录，无需单独安装 Node 或前端开发服务器。线上入口为 https://monitor.bocom-tokyo.site/ ，主域名 https://bocom-tokyo.site/ 自动跳转。当前共享测试账号为 `test`，密码为 `test`，由 Caddy 验证；本地服务仅绑定回环地址。

## 启动

需要 Python 3.11+。在本仓库目录打开 PowerShell：

```powershell
.\Setup.ps1
.\Start.ps1
```

打开 http://127.0.0.1:8000/ 。如本机策略不允许运行脚本，可用 `powershell -ExecutionPolicy Bypass -File .\Setup.ps1` 和同样方式运行 Start.ps1（仅对本次进程生效）。

验证模拟规则时点击“载入演示数据”，创建一条船舶、一条当天航班及一条明确标记的虚构公开信息，同时演示船舶进入区域和航班延误。后续分别点击船舶/航空面板的刷新按钮，或等待默认 30 分钟自动采集；直接使用 uvicorn 启动也采用此默认值。设置 `RISK_POLL_SECONDS=0` 可关闭。页面每 15 秒只读取本地记录，不调用外部数据源。修改已有 `.env` 的采集间隔后需重启。

列表展示船型、机型和客货用途；来源未提供时显示未分类，可在目标详情中维护。通过“目标与区域管理”删除或恢复目标及区域；删除停止采集并保留历史证据，恢复后保持暂停。在用区域（包括暂停目标引用）不能删除。字段对照、限制和偏差复盘见 [界面验收约定](docs/ui-acceptance.md)。

通过“添加监控对象”添加真实目标；模拟源的标识、MMSI、航班号仍不代表真实资产。数据库位于 `data/risk.db`，不提交 Git。测试使用临时数据库。

## 已实现

- 独立监控首页；根路径直接展示页面，旧 `/asset-risk.html`、`/demo.html` 重定向到根路径。
- 添加船舶、飞机实体、具体日期的航班、矩形风险区域；同一飞机实体可关联多天航班。
- 船舶区域内外判断、首次发现位于区域内、进入和离开事件；边界计入区域。
- 起飞/到达延误严格大于阈值触发，实际时间优先；取消、备降、状态恢复、延误恢复。
- 暂停/恢复监控、修改航班阈值并保留新规则版本；缺失、过期、乱序、重复和失败处理。
- 目标状态、离线世界地图、真实 AIS / ADS-B 与模拟位置、航班计划/预计/实际时间。动态与规则风险合并为原 demo 样式的彩色时间线，每页10条，支持类型/级别筛选与原始证据详情；同次采集不重复展示。
- 公开信息录入/API 导入，真实资料须含来源 URL；不把新闻自动当成已验证的资产异常。
- 可选 AI 分析、独立开关、自动刷新开关、失败保留上次结果、输入快照及调用审计。

未实现：官方商业数据 API、每日航班实例自动订阅、新闻自动接入、飞机历史轨迹回放、空域风险、航向异常、AIS 失联、多边形及跨日界线区域。不能依据这些未实现规则声称目标安全。底图采用随项目保存的 Natural Earth 陆地数据，支持缩放、拖动、定位目标；无需联网地图服务。飞机演示位置覆盖 HND–PVG / PVG–HND，其他航段无数据时不猜测。位置不依赖 AI，来源与投影见 `docs/map-data.md`。真实飞机按飞机实体单独添加，不把模拟航班自动切换成真实实例。

## AI（默认关闭）

将 `.env.example` 复制为 `.env`，填写 `AI_API_KEY` 和账号支持的 `AI_MODEL`；`AI_BASE_URL` 默认为 `https://api.deepseek.com`。启动脚本读取这些变量；若自行启动 uvicorn，应在进程环境中设置。重启后在页面开启 AI，点击更新；可选择资料变化后自动更新。

采用兼容 Chat Completions 的 HTTP 接口，见 [DeepSeek 官方文档](https://api-docs.deepseek.com/api/create-chat-completion/)。模型名称由账号实际可用列表决定，不在代码中固定。密钥只在服务端读取，页面、数据库和错误响应均不返回密钥。

未配置或关闭时不调用 AI。启用后手动触发或自动每分钟检查：只在输入变化时调用，调用至少间隔 60 秒，超时 20 秒。失败不会清空上次成功文本，也不阻塞普通监控；调用过程中关闭开关会丢弃该次结果。配置完成只表示具备参数，不表示已验证接口可达。

发送范围为最近最多 40 个监控对象、20 条事件、10 条公开信息，包含目标名称、状态、规则和记录 ID。启用即允许将这些资料交给配置的数据处理服务。AI 分析有独立生成时间和输入审计，不能替代实时事实。当前仅以模拟 HTTP 返回验证流程，尚未验证真实 AI 账号。

## 集成与交付

- API 文档：`/docs`；契约文件 `docs/openapi.json`。
- `GET /api/v1/dashboard` 为页面汇总；核心 API、ER 和 Provider 设计见 `docs/architecture.md`、`docs/api-contract.md`、`docs/provider-integration.md`。
- 页面与 API 由同一服务提供，见 `docs/portal-integration.md`。
- 页面资源仅来自 `/static/`，FastAPI 不公开仓库目录、数据库或环境文件。
- 本地版本绑定 127.0.0.1；服务器通过 Caddy 提供 HTTPS 和全站 Basic Auth，8000 端口不对外开放。当前使用共享测试账号，未建立独立用户和权限系统。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

本仓库保留最初静态蓝图的 Git 历史；部署方式见 `docs/server-test.md`。更新前备份代码、配置和数据库。
