"""Configure the standalone test site's entry points and existing service environment.

Run after backing up /etc/caddy and /etc/risk-monitor. Does not restart services.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess

DOMAIN = 'monitor.bocom-tokyo.site'
ALIASES = ('bocom-tokyo.site',)


def caddy_config(username, hashed_password):
    if not username.isalnum() or any(c.isspace() for c in hashed_password):
        raise ValueError('Invalid Caddy authentication values')
    return f'''{DOMAIN} {{
    encode gzip
    basicauth {{
        {username} {hashed_password}
    }}
    reverse_proxy 127.0.0.1:8000
    header {{
        X-Content-Type-Options nosniff
        Referrer-Policy same-origin
    }}
}}

{', '.join(ALIASES)} {{
    redir https://{DOMAIN}{{uri}} 308
}}
'''


def environment(text):
    values = {
        'RISK_ALLOWED_HOSTS': DOMAIN,
        'RISK_ALLOWED_ORIGINS': 'https://' + DOMAIN,
    }
    lines = []
    for line in text.splitlines():
        key = line.partition('=')[0].strip()
        if key == 'PUBLIC_DATA_CONTACT':
            continue
        if key in values:
            lines.append(key + '=' + values.pop(key))
        else:
            lines.append(line)
    lines.extend(key + '=' + value for key, value in values.items())
    return '\n'.join(lines) + '\n'


def write_atomic(path, content, mode):
    temp = path.with_name(path.name + '.next')
    temp.write_text(content, encoding='utf-8')
    temp.chmod(mode)
    os.replace(temp, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--username', default='test')
    parser.add_argument('--password', default='test')
    args = parser.parse_args()
    hashed = subprocess.run(['caddy', 'hash-password'], input=args.password + '\n',
                            text=True, capture_output=True, check=True).stdout.strip()
    caddy = Path('/etc/caddy/Caddyfile')
    candidate = caddy.with_name('Caddyfile.candidate')
    candidate.write_text(caddy_config(args.username, hashed), encoding='utf-8')
    candidate.chmod(0o644)
    try:
        subprocess.run(['caddy', 'validate', '--config', str(candidate), '--adapter', 'caddyfile'], check=True)
        env = Path('/etc/risk-monitor/service.env')
        write_atomic(env, environment(env.read_text()), 0o600)
        access = {'url': 'https://' + DOMAIN + '/', 'username': args.username, 'password': args.password}
        write_atomic(Path('/etc/risk-monitor/test-access.json'), json.dumps(access) + '\n', 0o600)
        os.replace(candidate, caddy)
    finally:
        candidate.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
