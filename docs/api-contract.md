# API Contract v1
前缀 /api/v1，JSON，时间为含时区 ISO 8601；统一 UTC 响应。
经纬度为度；GeoJSON 顺序 [longitude,latitude]。
完整契约见 openapi.json。新增 201，读取/操作 200。
错误：422 校验失败；404 不存在；409 重复、暂停或不适用操作。
校验错误 detail 为数组，预期业务错误 detail 为字符串。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | /health | 模式、调度、引擎 |
| GET / POST | /regions | 区域列表 / 新增矩形区域 |
| GET / POST | /monitors | 列表 / 新增对象 |
| GET / PATCH | /monitors/{id} | 详情 / enabled 开关 |
| POST | /monitors/{id}/rule-versions | 航班规则新版本 |
| POST | /monitors/{id}/poll | 真实源使用空请求体 `{}`；模拟源可指定场景；限频返回 throttled、raw_id=null |
| POST | /poll | 所有启用且未删除对象采集；可选 group=vessel 或 aviation，航空包括飞机实体和航班实例 |
| DELETE | /monitors/{id} | 停止采集并软删除；保留历史证据 |
| POST | /monitors/{id}/restore | 恢复目标，保持暂停 |
| PATCH | /monitors/{id}/profile | 维护船型、机型及客货用途，记配置审计 |
| DELETE | /regions/{id} | 软删除区域；存在未删除目标引用时返回 409 |
| POST | /regions/{id}/restore | 恢复区域 |
| GET | /events | monitor_id、kind、severity、since、until、limit、offset |
| GET | /events/{id} | 事件与证据 |

创建船舶：
```json
{"kind":"vessel","name":"演示船舶 A","imo":"9074729","region_id":"demo-zone"}
```
创建航班：
```json
{"kind":"flight","name":"演示航班 RM101","carrier":"RM","flight_number":"101","service_date":"2026-09-09","departure":"HND","arrival":"PVG","scheduled_departure":"2026-09-09T10:00:00+09:00","scheduled_arrival":"2026-09-09T13:00:00+09:00","threshold_minutes":60,"delay_basis":"departure"}
```
采集请求：{"scenario":"sequence"}；响应：{raw_id,outcome,events:[event_id]}。
船舶场景：outside/inside/boundary；航班：on_time/delayed/recovered/actual/cancelled/diverted；
共用：sequence/missing/stale/out_of_order/duplicate/failure。
事件字段：id、monitor_id、evaluation_id、rule_id、type、severity、occurred_at、created_at、summary、evidence。
occurred_at 是触发观察时间，并非推测的真实跨界时刻。severity 是演示规则等级。
列表为 {items,total,limit,offset}；详情最多返回最近 50 状态/评估、20 原始记录、50 配置变更，完整历史在数据库中。
监控列表首版无分页，适合小规模本地原型。

`GET /monitors` 和 `GET /regions` 默认不包含已删除项，可用 `include_deleted=true` 查询管理列表。目标详情及历史事件继续可查。区域返回 `monitor_names` 供展示引用关系。

创建目标可含 `profile`；维护接口接受同一结构，例如 `{"vessel_type":"container"}` 或 `{"aircraft_model":"B777","aircraft_role":"passenger"}`。维护接口完整替换人工维护值，未传/空值回退到来源信息。响应中的 `business` 是统一展示结构（category、category_label、aircraft_model、category_source、model_source），人工值优先、来源值其次，缺失不猜测。字段枚举详见 OpenAPI。分类不参与确定性风险判断。


## 公开真实数据扩展

- `GET /api/v1/public/sources` 返回来源名称、文档链接、许可和 live 标记。
- `GET /api/v1/public/targets` 返回 `{items, errors, sources}`。items 为近期可见目标，包含 kind、provider、name、坐标、observed_at；船舶包含 mmsi，飞机包含 aircraft_registration、icao24、callsign、aircraft_type。部分源失败时可返回另一源的候选，errors 提示失败。
- 创建目标新增 provider（默认 mock-v1）。digitraffic-v1 限 vessel 且必须填 mmsi；adsblol-v1 限 aircraft 且必须填 aircraft_registration 和 icao24。
- aircraft 监控关联 asset_id，flight_id=null，没有计划时刻；对应 state 明确 flight_risk_assessed=false。Observation 可包含 callsign、aircraft_type。
- 时间线每条返回 provider；health.mode 为 mock / live / mixed，按启用目标的数据源统计。
- 调用限制与原始响应审计见 [公开数据接入](public-data.md)。


数据源注册表扩展：`GET /public/sources` 的各项包含 kinds、capabilities（按类型）、required_fields（按类型）、is_mock、min_poll_seconds、max_age_seconds 和来源署名。Monitor 和 Timeline 含 source 对象；具体适配器注册与边界见 [数据源边界](provider-boundary.md)。
