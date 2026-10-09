# API 契约

以 `docs/openapi.json` 及运行服务 `/docs` 为准。

- `POST /api/v1/monitors`：`{"kind":"vessel","identifier_type":"imo","identifier":"9811000","remark":""}`；船舶可选 imo / mmsi，界面默认 IMO。飞机为 aircraft + registration。必填前三项，备注可省略；外部不再接受 ship_id。
- 查询核验后创建并执行首次采集。来源暂时不可用 503；格式、查无结果、匹配不唯一或身份冲突 422；重复目标 409。已经核实身份但首次定位失败时，创建仍成功，详情显示采集状态。
- `GET /monitors`、`GET /monitors/{id}`；后者包含原始记录、历史评估与配置审计。`regions` 为适用的全部有效区域；不再返回单个绑定 region。
- `PATCH /monitors/{id}` 控制 enabled；`PATCH /monitors/{id}/remark` 修改可选备注；`POST /monitors/{id}/rule-versions` 修改航空延误阈值。
- `DELETE /monitors/{id}`、`POST /monitors/{id}/restore` 软删除/恢复。
- `GET/POST /regions` 查询/新增矩形围栏，新增适用全部船舶；`DELETE /regions/{id}`、`POST /regions/{id}/restore` 删除/恢复。已有默认围栏为多边形。
- `GET /dashboard` 返回 updated_at、monitors、regions、events；不触发外部采集。`GET /timeline` 提供快照分页及 kind/entry_type/severity 筛选。
- `GET /events`、`GET /events/{id}` 查看事件与原始证据。
- `POST /poll?group=vessel|aviation` 和 `POST /monitors/{id}/poll` 为运维采集接口，不再接受模拟场景；页面使用自动采集。
- `GET /health` 返回 scheduler_seconds；`GET /public/sources` 仅两个供应商。

演示、公开信息、AI 以及手工分类写入接口已移除。非配置来源的跨站写请求返回 403；服务器全站 Basic Auth 位于 Caddy。
