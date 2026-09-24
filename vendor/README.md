# 固定版本 SDK

本目录保存本次实际测试的安装包与许可证。应用从 `backend/requirements-sdk.txt` 安装，避免本机和服务器运行不同源码。

| 安装包 | SHA256 |
|---|---|
| flightradarapi-1.6.1-py3-none-any.whl | c494c5a668056f9f7466a1e7144e8c77a78277fe434e5aa5a11357beb0755786 |
| marinetrafficapi-0.1.0-py3-none-any.whl | a42f78c9b7cc0286ab8e9f61bc6f14fe71bca8045272f225791f942ff12e7ab4 |

FlightRadarAPI 从用户本地源码构建；MarineTrafficAPI 使用用户本地 0.1.0 构建产物。升级时替换包、版本及哈希，更新依赖清单并执行适配器测试；不要在版本不变时假定 pip 自动覆盖旧包。MIT 代码许可不等同于上游数据授权。
