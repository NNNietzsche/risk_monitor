2026-10-09 17:03 JST 船舶请求预算修复发布；本地和服务器各 110 项后端测试通过。备份 `/var/backups/risk-monitor/20261009T080154Z-marine-budget`，业务数据内容不变。页面仍沿用添加选项卡版本，新增拒绝访问后的来源等待。

2026-10-09 添加入口版本 `20261009-enrollment1` 已发布；本地和服务器各 106 项后端测试、17 项前端测试通过。备份 `/var/backups/risk-monitor/20261009T021502Z-enrollment`，业务数据内容摘要不变。

# 服务器与发布

2026-10-09 09:36 JST 已发布批量位置、分散采集与延误显示修复，页面版本 `20261009-batch1`。Windows 与服务器各 107 项后端测试、17 项前端测试通过。备份 `/var/backups/risk-monitor/20261009T003517Z-batch`，全部 12 张监控业务表内容摘要保持一致。完整历史校验必须逐行计算，避免把当前 1.1 GB 数据库读入内存；独立 systemd 发布任务退出后确保应用服务启动。

服务器 45.77.8.153，HTTPS 入口 https://monitor.bocom-tokyo.site/ 。主域名 https://bocom-tokyo.site/ 跳转到该子域名。反向代理是 Caddy，非 Nginx；Basic Auth 测试账号 test / test。旧路径 /demo.html、/asset-risk.html 重定向根路径。

- 应用目录 /opt/risk-monitor，Python 虚拟环境 .venv。
- systemd 服务 risk-monitor，运行用户 riskmonitor，单 Uvicorn worker，回环 127.0.0.1:8000。
- SQLite /var/lib/risk-monitor/risk.db；配置 /etc/risk-monitor/service.env。
- Caddy /etc/caddy/Caddyfile；登录配置 /etc/risk-monitor/test-access.json。不可将配置中的秘密输出或打入公开发布包。
- RISK_POLL_SECONDS=600；按目标分散时隙执行，FR24 基础位置批量获取、详情分散请求，全部端点共享间隔与 429 退避；页面自动读取本地数据，无额外供应商请求。

当前更新：先本地测试和线上数据库副本迁移演练；服务器独立暂存目录复跑测试；停止服务后备份代码、配置、SQLite，部署并启动。检查核心历史表的数量和内容摘要、全部既有目标 ID、外键、默认区域、登录、重定向和线上页面。失败恢复应用、配置和数据库。Caddy 配置无须改动。

首次安装可使用 deploy/install-server.sh；默认空资产列表与两个围栏，不自动导入样例目标。生产已有资产保持原 ID 与数据。

本次核心版本已于 2026-09-30 12:43 JST 发布，备份：`/var/backups/risk-monitor/20260930T034311Z-core`。本地与服务器 87 项后端测试、11 项页面/地图测试通过；详情见 validation.md。

本轮已于 2026-09-30 13:55 JST 发布。服务器同一 88 项后端测试通过；前端 16 项测试通过。发布备份 `/var/backups/risk-monitor/20260930T045542Z-layout`。迁移前后全部 12 张监控业务表内容摘要一致：6 个目标、1,215 条原始采集、758 条观察、758 条评估、3 条事件等全部保留。public_news、ai_runs、ai_settings 已删除，数据库版本为 6，外键及完整性检查通过。正式页面经浏览器验证 3 艘/3 架、浅色提示、2:1 地图、独立跳页及返回最新，应用脚本无报错；浏览器日志有来自广告拦截扩展的上下文失效记录，与应用无关。采集仍每 600 秒，本轮没有额外手动触发供应商采集。
