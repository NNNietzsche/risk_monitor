# 独立测试服务器

2026-09-30 更新：系统独立运行，入口与认证按用户要求调整。

- 正式测试入口：`https://monitor.bocom-tokyo.site/`，首页直接展示监控页面。
- `https://bocom-tokyo.site/` 以 308 跳转到新子域名；同域名旧页面路径 `/asset-risk.html`、`/demo.html` 以 308 跳转到 `/`。
- 用户已将旧子域名 DNS 记录改名为 `monitor`。旧 `risk-monitor` 子域名不再配置或申请证书。
- 账号 `test`，密码 `test`；由 Caddy 全站 Basic Auth 保护页面、静态资源及 API。访问凭据文件为服务器 `/etc/risk-monitor/test-access.json`（0600）及本地被 Git 忽略的 `data/server-access.json`。
- 主机：45.77.8.153。代码 `/opt/risk-monitor`；数据库 `/var/lib/risk-monitor/risk.db`；配置 `/etc/risk-monitor/service.env`。
- systemd 服务 `risk-monitor`，以 riskmonitor 用户运行，单 worker，绑定 `127.0.0.1:8000`。Caddy 对外提供 80/443，自动管理 HTTPS；8000 不公开。
- 自动采集 600 秒；启动后等待首个周期。船舶/航空分别手动刷新。页面与详情读取不调用供应商。
- 保留既有两艘船、两架飞机、观测、规则和原始证据；本轮不修改 SDK，不重新导入或采集样例，AI 保持关闭。

`deploy/configure-site.py` 生成 Caddy 配置并更新域名白名单和测试账号；更新环境变量时保留现有数据库路径、采集间隔和其他配置。它只配置，不重启服务。

`deploy/install-server.sh` 用于初始化安装，需要预装 caddy、python3-venv。现有站点更新须先使用 SQLite backup 备份数据库，并备份代码及 `/etc/caddy/Caddyfile`、`/etc/risk-monitor`；不要将本地 `.env` 或数据库上传覆盖服务器数据。部署包仅含代码、静态资源、文档、测试和固定依赖。

常用运维：`systemctl status risk-monitor caddy`、`journalctl -u risk-monitor -n 80`。修改代码或环境后重启 risk-monitor；修改 Caddy 配置先 validate，再 reload。共享账号仍用于测试，未增加用户权限系统。
