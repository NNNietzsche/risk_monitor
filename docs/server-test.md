# 测试服务器

- 域名：`https://risk-monitor.bocom-tokyo.site/asset-risk.html`
- 主机：45.77.8.153；保留 SSH 配置，未改动根域名及 www 的站点用途。
- 代码 `/opt/risk-monitor`；数据库 `/var/lib/risk-monitor/risk.db`；配置 `/etc/risk-monitor/service.env`。
- systemd 服务 `risk-monitor`，非 root 运行，单 worker，绑定 `127.0.0.1:8000`。Caddy 提供 HTTPS 及全站 Basic Auth；外部不开放 8000。
- 自动采集 1800 秒；启动后等待首个周期。手动刷新船舶/航空分别调用 `/api/v1/poll?group=vessel|aviation`。
- 未配置 AI 密钥。使用独立新数据库导入本次测试清单，不上传本地历史数据库、联系人、.env 或其他项目资料。
- 随机测试凭据仅保存服务器 `/etc/risk-monitor/test-access.json`（0600）及本地被 Git 忽略的 `data/server-access.json`。正式多人使用需接宿主身份权限；本次仅共享测试账号。

部署脚本：`deploy/install-server.sh`。发布包上传至 `/tmp/risk-monitor-release.tar.gz`，先核对目标主机、变更和测试结果再运行。脚本安装项目依赖、配置服务和 HTTPS 并开放 80/443；部署前系统依赖为 Ubuntu 的 caddy、python3-venv。不会清空数据库或重新生成现有测试密码。

常用运维：`systemctl status risk-monitor caddy`；`journalctl -u risk-monitor -n 80`；`systemctl restart risk-monitor`。更新前用 SQLite backup 备份数据库，不直接复制正在写入的数据库文件。

测试数据、备份、访问密码不得提交 Git；轮换密码后同步 Caddy 哈希配置并 reload。
