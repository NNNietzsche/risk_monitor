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
| POST | /monitors/{id}/poll | 指定模拟场景 |
| POST | /poll | 所有启用对象推进序列 |
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
