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

每次请求仅执行一次，不设置最短请求间隔、成功缓存、固定失败冷却或空结果隐式重试。外部周期默认 600 秒；当前公开网页接口并非购买的官方商业 API。HTTP 403/429 等失败仍如实记录，不能推断是请求频率导致。

补充信息错误不丢弃有效主船位；数据源失败不覆盖已确认的历史位置。原始 JSON/响应字节保存在采集证据中，身份核验响应保存在配置审计中。
