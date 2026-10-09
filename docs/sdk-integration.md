# SDK 接入与后续同步

本轮不更换用户仍在完善的 SDK 包；版本以 `backend/requirements-sdk.txt` 和 vendor wheel 为准。

| 数据 | 当前调用方式 |
|---|---|
| 船位 | 固定 MarineTraffic SDK 的 MarineTrafficClient.get_position(shipId) |
| 船舶标识解析 | 适配层 `/en/global_search/search?term=...`，按 IMO/MMSI 类型与号码精确匹配，随后核查 general |
| 船名、船型、尺寸、船旗 | 适配层 `/en/vessels/{shipId}/general` |
| 航次和时间 | 适配层 `/en/vessels/{shipId}/voyage` |
| 港口名称与代码 | 适配层 `/en/ais/get_info_window_json?asset_type=ship&id=...`，与航次港口 ID 匹配 |
| 飞机实时位置 | FlightRadarAPI 的 APIRequest、FlightTrackerConfig 与 Flight 实体解析 |
| 最近/待飞航班 | FR24 注册号 flight/list.json，核对注册号、时间窗口及实际起降时间 |
| 机场名称、起降时刻 | FR24 航班详情；与实时 flight ID、注册号、航班号和起降机场匹配后合并 |
| 飞机分类 | FR24 页面使用的分类接口，核对 registration / flight ID；不从机型猜测 |

MarineTraffic 补充路径与用户新版 SDK 的 get_search/get_general/get_voyage/get_info 对应，暂由 `marine_details.py` 调用；SDK 完善后可替换此边界，保持标准化 Observation、身份检查和原始证据不变。

每次请求仅执行一次，不做空结果隐式重试。按 600 秒周期分散逐架详情与历史查询，基础位置用逗号分隔注册号批量获取，最长 600 秒共享同一原始批次。已验证近期历史包含完整详情时省去重复 clickhandler。全部 FR24 端点和身份查询共享 3 秒间隔，429 尊重 Retry-After 并用 60～900 秒递增退避兜底；403 等其他失败仍如实记录。3 秒是本项目保守策略，不是供应商承诺的额度。

MarineTraffic 的身份搜索、核验、主船位和每个补充请求也共享独立 3 秒间隔，403/429 来源整体冷却并尊重 Retry-After，兜底 60～900 秒递增退避。补充信息被拒绝后停止剩余补充查询，保留已取得主船位；未发请求不写新响应。身份查询被拒绝时不创建目标，返回剩余等待秒数。新增或停用目标后，下一次调度按当前同来源启用数量计算 600/N；已经预约的下一个时隙保留，首次创建采集仍立即执行但遵守请求间隔。

固定安装的 FlightRadarAPI 1.6.1 确有可选 RetryPolicy（默认关闭，临时网络错误/CloudflareError 指数退避及 jitter），另有空 feed 最多四次重查。当前适配器直接使用 APIRequest，保留原始 HTTP 状态并由应用的来源级预算控制；不叠加 SDK 隐式重试，避免一次任务产生多次未计入间隔的请求。SDK 的空结果重查不等同于 429 的 Retry-After/来源整体冷却。

2026-10-09 在现有服务器实测，29 个注册号一次 feed.js 请求返回 10 架有实时定位的飞机，未混入其他注册号，单查核对通过。SDK get_flights(details=True) 仍逐架请求详情；官方商业 API 支持 registrations 列表过滤，但当前未接入该付费接口，也未使用其额度。

补充信息错误不丢弃有效主船位；数据源失败不覆盖已确认的历史位置。原始 JSON/响应字节保存在采集证据中，身份核验响应保存在配置审计中。
