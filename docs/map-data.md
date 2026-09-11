# 离线世界底图

`static/world-land.svg` 由 Natural Earth 1:110m land GeoJSON 生成，仅展示陆地和海岸线，无国界。

- 数据来源：https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_land.geojson
- 下载日期：2026-09-11
- 原始 GeoJSON SHA256：`9e0729ee253ca7d7a5c4ae9395fb1902264c5377c52e224d13dd85010e2835d9`
- 授权：公共领域，https://www.naturalearthdata.com/about/terms-of-use/
- 投影：等距圆柱，经度 x=(lon+180)×2，纬度 y=(90-lat)×2；画布720×360。小数保留两位。区域和目标采用同一投影。

底图在本地加载，不需要在线瓦片、地图密钥或 CDN。低精度陆地轮廓只用于位置概览，不适合航海/航空导航；放大不会增加地理细节。

飞机 Mock 仅为 HND–PVG / PVG–HND 演示航段提供合成位置序列，位置不是实测或实际飞行路线，机场端点也不是精确机场测绘坐标。未知航段不猜测位置。取消和缺失场景不提供新位置；页面会区分无定位与历史定位。新增位置字段沿用标准化 Observation 的经纬度，不依赖 AI。
