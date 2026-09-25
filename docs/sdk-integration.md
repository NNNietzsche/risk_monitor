# 实验 SDK 接入（2026-09-24）

2026-09-25 更新：飞机样例已改为按注册号持续跟踪，当前能力和迁移方式见 [aircraft-tracking.md](aircraft-tracking.md)。下文固定日期航班样例和人工分类为 9 月 24 日的历史记录；新清单为 deploy/test-targets-20260925.json。

`FlightRadarAPI 1.6.1` 来自本机 `C:/develop/FlightRadarAPI/python` 的源码构建；`MarineTrafficAPI 0.1.0` 来自本地半成品 SDK 的 wheel。固定安装包保存在 vendor，`backend/requirements-sdk.txt` 是安装入口，不从同名陌生 PyPI 包安装 MarineTrafficAPI。

## 分层和更新

```text
SDK → backend/sdk_providers.py → Observation → 现有规则/证据存储 → 既有 API → 页面
```

Provider 注册统一维护支持类型、必填身份、来源名称、采集间隔和数据年龄。前端不解析 SDK 原始返回。升级 SDK：构建新 wheel，更新 requirements-sdk.txt，跑 test_sdk_providers.py 和实网单次验证，重新安装并重启。返回字段改名时只修改适配器；增加新的业务能力时，需要显式扩展 Observation、规则和 API 契约。这里已有进程内中间层，尚未建立独立通用数据服务；未来可增加 HTTP Provider 接独立服务而保留业务规则。

## 身份与证据

- MarineTraffic 的 shipId 是外部映射 `source_ref`，业务船舶身份仍为 IMO/MMSI。映射随创建请求及配置审计保存，位置响应校验 shipId；响应提供 IMO/MMSI 时也校验。此 SDK 暂无按 IMO/MMSI 搜索能力，映射应预先核实。
- FR24 飞机实体按注册号查，填有 ICAO24 时同时核对。当天航班按 flight ID、航班号、起止机场和计划时刻核对；不把相同航班号的不同日期串接。关联注册号变化时提示核对，不静默换飞机。
- 30 分钟自动采集，类别手动刷新保留；本源每目标最短间隔 5 分钟，共享请求缓存 120 秒。失败后本源至少冷却 30 分钟，429 遵守更长 Retry-After；不执行即时重试。冷却在进程内，目标最短采集间隔在数据库持久化。部署仅运行一个 worker。
- SDK 原始 JSON 在标准化前存储。FR24 另保留 SDK 暴露的响应字节和状态；MarineTraffic SDK 不暴露 HTTP 原始字节和成功响应头，当前保留其完整 JSON，证据中明确这一限制。未使用个人 Cookie、登录或代理。
- FR24 使用 SDK 的 APIRequest 和 Flight 解析器，避免 get_flights 的隐式空结果多次重试；请求范围和次数由适配器控制。
- 位置时间来自上游 timestamp/trail.ts，绝不用请求时间冒充。航班的 observed_at 为最新 trail 时间与 time.other.updated 的较大值，表示该来源快照的最新已知更新时间，不代表每个时刻字段都在此时变化；地图另保留 position_observed_at 判断历史位置。新源允许最多 1 小时数据年龄，自动周期为 30 分钟，超龄不触发规则。
- 航班延误由普通程序计算，实际优先预计；取消/备降取结构化状态，不解析自然语言文案猜测。AI 保持关闭。

## 本次样例

清单为 `deploy/test-targets-20260924.json`，是 2026-09-24 的显式测试样例，不是每天自动更新的航班订阅。

| 对象 | 业务身份 / 航线 | 来源映射 |
|---|---|---|
| COSCO SHIPPING UNIVERSE | IMO 9795610 / MMSI 477157400 | shipId 5554510 |
| EVER GIVEN | IMO 9811000 / MMSI 636026627 | shipId 5630138 |
| NH8501，2026-09-24 | 东京成田 NRT → 大连 DLC；JA602F | flight ID 41ceb9e3 |
| HO1380，2026-09-24 | 东京成田 NRT → 上海浦东 PVG；B-20EC | flight ID 41ceb569 |

船舶类型根据已核实的公开船舶资料维护为集装箱船。NH8501 当前机型详情为 Boeing 767-381F(ER)，并与 ANA Cargo 的货运班号资料交叉核对，样例人工维护为货机；没有将 B763 通用型号作为自动推断规则。HO1380 用途未由接口明确提供，暂留未分类。

身份资料：[COSCO 船舶映射记录](https://www.marinetraffic.com/en/ais/details/ships/shipid:5554510/mmsi:477157400/imo:9795610/vessel:COSCO_SHIPPING_UNIVERSE)、[船舶资料](https://www.vesselfinder.com/vessels/details/9795610)、[EVER GIVEN](https://www.marinetraffic.com/en/ais/details/ships/shipid:5630138)、[ANA Cargo 历史班号资料](https://www.anacargo.jp/ja/int/timesheet/upload/2019/0319/ANAcargo_19S.pdf)。本次航班日期与实际时刻来自实时 SDK 响应，未采用历史时刻表作为当前计划。

显式注册（不自动查询上游）：

```text
python -m backend.sample_targets --file deploy/test-targets-20260924.json
```

需要立即查询时加 `--poll`，只采集清单中目标。日期过后这些记录仍是当日航班，过期会如实提示；不会自动创建次日航班。船舶使用“红海测试围栏（仅联调，非风险评级）”，不是银行核准的风险区域。

本次是非官方接口的受保护测试部署，不代表取得正式商业数据授权。网站接口、覆盖和可用性仍需持续验证。[FlightRadarAPI 项目说明](https://github.com/JeanExtreme002/FlightRadarAPI)明确区分实验 SDK 与官方商业 API。
