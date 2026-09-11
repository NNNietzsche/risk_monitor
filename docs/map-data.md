# 离线世界底图

`static/world-land.svg` 由 Natural Earth 1:110m land GeoJSON 生成，仅展示陆地和海岸线，无国界。

- 数据来源：https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_land.geojson
- 下载日期：2026-09-11
- 原始 GeoJSON SHA256：`9e0729ee253ca7d7a5c4ae9395fb1902264c5377c52e224d13dd85010e2835d9`
- 授权：公共领域，https://www.naturalearthdata.com/about/terms-of-use/
- 投影：等距圆柱，经度 x=(lon+180)×2，纬度 y=(90-lat)×2；画布720×360。小数保留两位。区域和目标采用同一投影。

底图在本地加载，不需要在线瓦片、地图密钥或 CDN。低精度陆地轮廓只用于位置概览，不适合航海/航空导航；放大不会增加地理细节。

飞机 Mock 仅为 HND–PVG / PVG–HND 演示航段提供合成位置序列，位置不是实测或实际飞行路线，机场端点也不是精确机场测绘坐标。未知航段不猜测位置。取消和缺失场景不提供新位置；页面会区分无定位与历史定位。新增位置字段沿用标准化 Observation 的经纬度，不依赖 AI。


## 列表位置名称

`static/places.json` 使用 Natural Earth 陆地及海洋标注多边形，以中文 name_zh 优先。海域来源：https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_geography_marine_polys.geojson ，下载于 2026-09-11，原文件 SHA256 `53f865e8ffa966cdd402145c82c5cd14ee7ce974cd0eb9a3f59f03a4cfd2d66c`。与底图同为公共领域数据，说明：https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-physical-labels/ 。保留环和空洞，坐标保留4位小数。

先排除低精度陆地范围，再按包含定位点的最小多边形选择海域名称；未命中显示“海域未知”，无定位显示“暂无定位”。这是供阅读的粗略位置说明，不是海域边界认定或新的风险规则，沿岸精度受底图限制。旧定位明确标注“历史”，不替代数据质量状态。

默认 demo-zone 的普通模拟点调整为区内 (47,12) 亚丁湾、区外 (52,12) 阿拉伯海，使后续演示位置处于海上。区内外循环、边界场景、自定义区域和既有历史记录保留原有行为。经纬度和规则参数移到详情，列表仅展示标识、状态和大致海域/起止机场；卡片数量包含暂停目标，悬停数量可查看其中启用数。

机场名称为可扩展的小型离线字典：东京羽田 HND、上海浦东 PVG、上海虹桥 SHA；未知代码原样显示。依据：[羽田机场官网](https://www.tokyo-haneda.com/zh-CHS/index.html)、[上海市教育委员会机场说明](https://edu.sh.gov.cn/study_en_living/20240808/959f13ec112644e59624968c673f6b7c.html)。机型等未接入的字段不猜测填充。
