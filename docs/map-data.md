# 地图、默认围栏与标识

底图 `static/world-land.svg` 来自 Natural Earth 1:110m land；海域名称 `static/places.json` 来自其 1:10m marine polygons。公共领域数据，等距圆柱投影 x=(lon+180)×2、y=(90-lat)×2。坐标与所有区域使用同一投影，地图容器固定 2:1 比例，初始完整显示世界范围。普通滚轮滚动页面，Ctrl＋滚轮（Mac 也支持 Command）围绕指针缩放；保留加减和全球复位按钮。鼠标拖动不选中文字，触屏单指保留页面纵向滚动。目标高亮不改变视野。

- [Natural Earth 授权](https://www.naturalearthdata.com/about/terms-of-use/)
- [陆地源数据](https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_land.geojson)，2026-09-11 下载，SHA256 `9e0729ee253ca7d7a5c4ae9395fb1902264c5377c52e224d13dd85010e2835d9`。
- [海域源数据](https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_geography_marine_polys.geojson)，SHA256 `53f865e8ffa966cdd402145c82c5cd14ee7ce974cd0eb9a3f59f03a4cfd2d66c`。

`backend/default_regions.json` 定义两个初始监控围栏：亚丁湾沿用现有 Natural Earth 海域标注多边形；霍尔木兹海峡使用覆盖通道及东西接近水域的近似多边形，范围约东经 55.85–57.25、北纬 25.55–27.05。两者是用户要求的业务监控范围，不是官方风险评级、领海边界或航海导航数据。边界点计入区域，图形与后端判断一致。

机场名称优先常用中文映射，否则采用接口原名，始终附 IATA 代号；未提供名称时明确说明，不猜测翻译。

页头标识使用[交通银行东京分行官网](https://www.jp.bankcomm.com/BankCommSite/shtml/jp/cn/2600534/list.shtml?channelId=2600534)引用的[原始 PNG](https://www.jp.bankcomm.com/BankCommSite/shtml/jp/cn/img/logo_img_1004.png)，本地保留完整图片，以 CSS 显示左侧图形标识；不重绘标志。
