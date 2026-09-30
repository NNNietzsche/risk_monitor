#!/usr/bin/env bash
set -euo pipefail
# Run on the designated test host as root after uploading risk-monitor-release.tar.gz.
APP=/opt/risk-monitor
DOMAIN=monitor.bocom-tokyo.site
if ! id riskmonitor >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/risk-monitor --create-home --shell /usr/sbin/nologin riskmonitor
fi
install -d -m 755 "$APP" /etc/risk-monitor
install -d -o riskmonitor -g riskmonitor -m 750 /var/lib/risk-monitor
tar -xzf /tmp/risk-monitor-release.tar.gz -C "$APP"
# Retired source code must not remain in an existing installation.
rm -f "$APP/backend/live_providers.py" "$APP/static/public-targets.js" "$APP/tests/test_live_data.py"
python3 -m venv "$APP/.venv"
cd "$APP"
.venv/bin/python -m pip install -r backend/requirements.lock.txt -r backend/requirements-sdk.txt
if [ ! -f /etc/risk-monitor/service.env ]; then
cat > /etc/risk-monitor/service.env <<EOF
RISK_DB_PATH=/var/lib/risk-monitor/risk.db
RISK_POLL_SECONDS=600
RISK_ALLOWED_HOSTS=$DOMAIN
RISK_ALLOWED_ORIGINS=https://$DOMAIN
PYTHONUNBUFFERED=1
PYTHONDONTWRITEBYTECODE=1
EOF
fi
chmod 600 /etc/risk-monitor/service.env
cat > /etc/systemd/system/risk-monitor.service <<'EOF'
[Unit]
Description=Asset risk monitor test service
After=network-online.target
Wants=network-online.target
[Service]
User=riskmonitor
Group=riskmonitor
WorkingDirectory=/opt/risk-monitor
EnvironmentFile=/etc/risk-monitor/service.env
ExecStart=/opt/risk-monitor/.venv/bin/python -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=on-failure
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/risk-monitor
UMask=0077
[Install]
WantedBy=multi-user.target
EOF
python3 deploy/configure-site.py --username test --password test
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
if [ ! -f /var/lib/risk-monitor/risk.db ]; then
  runuser -u riskmonitor -- .venv/bin/python -m backend.sample_targets --file deploy/test-targets-20260925.json --db /var/lib/risk-monitor/risk.db
fi
systemctl daemon-reload
systemctl enable --now risk-monitor
systemctl restart risk-monitor
systemctl reload caddy
ufw allow 80/tcp
ufw allow 443/tcp
systemctl is-active risk-monitor caddy
