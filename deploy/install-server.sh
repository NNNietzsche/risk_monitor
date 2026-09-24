#!/usr/bin/env bash
set -euo pipefail
# Run on the designated test host as root after uploading risk-monitor-release.tar.gz.
APP=/opt/risk-monitor
DOMAIN=risk-monitor.bocom-tokyo.site
if ! id riskmonitor >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/risk-monitor --create-home --shell /usr/sbin/nologin riskmonitor
fi
install -d -m 755 "$APP" /etc/risk-monitor
install -d -o riskmonitor -g riskmonitor -m 750 /var/lib/risk-monitor
tar -xzf /tmp/risk-monitor-release.tar.gz -C "$APP"
python3 -m venv "$APP/.venv"
cd "$APP"
.venv/bin/python -m pip install -r backend/requirements.lock.txt -r backend/requirements-sdk.txt
cat > /etc/risk-monitor/service.env <<EOF
RISK_DB_PATH=/var/lib/risk-monitor/risk.db
RISK_POLL_SECONDS=1800
RISK_ALLOWED_HOSTS=$DOMAIN
RISK_ALLOWED_ORIGINS=https://$DOMAIN
PYTHONUNBUFFERED=1
PYTHONDONTWRITEBYTECODE=1
EOF
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
python3 - <<'PY'
from pathlib import Path
import secrets,json,subprocess,os
path=Path('/etc/risk-monitor/test-access.json')
if not path.exists():
    path.write_text(json.dumps({'url':'https://risk-monitor.bocom-tokyo.site/asset-risk.html','username':'tester','password':secrets.token_urlsafe(24)}))
    path.chmod(0o600)
credentials=json.loads(path.read_text())
hashed=subprocess.run(['caddy','hash-password'],input=credentials['password']+'\n',text=True,capture_output=True,check=True).stdout.strip()
config='risk-monitor.bocom-tokyo.site {\n    encode gzip\n    basicauth {\n        tester '+hashed+'\n    }\n    reverse_proxy 127.0.0.1:8000\n    header {\n        X-Content-Type-Options nosniff\n        Referrer-Policy same-origin\n    }\n}\n'
file=Path('/etc/caddy/Caddyfile');file.write_text(config)
PY
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
runuser -u riskmonitor -- .venv/bin/python -m backend.sample_targets --file deploy/test-targets-20260924.json --db /var/lib/risk-monitor/risk.db
systemctl daemon-reload
systemctl enable --now risk-monitor
systemctl restart risk-monitor
systemctl reload caddy
ufw allow 80/tcp
ufw allow 443/tcp
systemctl is-active risk-monitor caddy
