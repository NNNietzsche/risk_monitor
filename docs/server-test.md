# 服务器与发布

服务器 45.77.8.153，HTTPS 入口 https://monitor.bocom-tokyo.site/ 。主域名 https://bocom-tokyo.site/ 跳转到该子域名。反向代理是 Caddy，非 Nginx；Basic Auth 测试账号 test / test。旧路径 /demo.html、/asset-risk.html 重定向根路径。

- 应用目录 /opt/risk-monitor，Python 虚拟环境 .venv。
- systemd 服务 risk-monitor，运行用户 riskmonitor，单 Uvicorn worker，回环 127.0.0.1:8000。
- SQLite /var/lib/risk-monitor/risk.db；配置 /etc/risk-monitor/service.env。
- Caddy /etc/caddy/Caddyfile；登录配置 /etc/risk-monitor/test-access.json。不可将配置中的秘密输出或打入公开发布包。
- RISK_POLL_SECONDS=600；页面自动读取本地数据，无额外供应商请求。

当前更新：先本地测试和线上数据库副本迁移演练；服务器独立暂存目录复跑测试；停止服务后备份代码、配置、SQLite，部署并启动。检查核心历史表的数量和内容摘要、四个既有目标 ID、外键、默认区域、登录、重定向和线上页面。失败恢复应用、配置和数据库。Caddy 配置无须改动。

首次安装可使用 deploy/install-server.sh；默认空资产列表与两个围栏，不自动导入样例目标。生产已有资产保持原 ID 与数据。

本次核心版本已于 2026-09-30 12:43 JST 发布，备份：`/var/backups/risk-monitor/20260930T034311Z-core`。本地与服务器 87 项后端测试、11 项页面/地图测试通过；详情见 validation.md。
