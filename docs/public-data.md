# 数据来源

2026-09-30 起只保留两个真实数据适配器：

- Flightradar24（FlightRadarAPI）：按注册号持续获取飞机位置、当前航班及可用的起降时刻；飞机类型及分类来自接口。
- MarineTraffic API：按核实后的 shipId 获取船舶位置；IMO/MMSI 仍为业务身份。

两者均为实验 SDK 接入，具体能力、失败冷却和证据范围见 [sdk-integration.md](sdk-integration.md) 与 [aircraft-tracking.md](aircraft-tracking.md)。页面简短介绍不改变数据授权或可用性边界。

Digitraffic / ADSB.lol 接入、PUBLIC_DATA_CONTACT 配置、候选发现 API 和“接入公开数据”按钮已移除。已有历史记录不删除。新目标使用“添加监控对象”；模拟源仅用于显式演示和测试。
