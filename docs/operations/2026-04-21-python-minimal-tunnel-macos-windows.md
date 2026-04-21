# Python Minimal Tunnel (macOS + Windows Client)

## Goal

Build a minimal tunnel without extra software:

- server: `scripts/tunnel/server_tunnel.py` on cloud host
- client: `scripts/tunnel/client_proxy.py` on macOS/Windows
- app traffic uses local HTTP CONNECT proxy (`127.0.0.1:7890`)

This avoids direct client-to-`x.com/chatgpt.com` first-hop exposure.

## 1) Server Deploy (54.169.43.149)

### 1.1 Copy scripts to server

```bash
scp -i ./LightsailDefaultKey-ap-southeast-1.pem \
  ./scripts/tunnel/server_tunnel.py \
  ubuntu@54.169.43.149:/home/ubuntu/
```

### 1.2 Create certificate (self-signed)

```bash
ssh -i ./LightsailDefaultKey-ap-southeast-1.pem ubuntu@54.169.43.149
mkdir -p ~/py-tunnel
openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 365 \
  -keyout ~/py-tunnel/server.key \
  -out ~/py-tunnel/server.crt \
  -subj "/CN=54.169.43.149"
```

### 1.3 Start server

```bash
export TUNNEL_TOKEN='CHANGE_THIS_TO_RANDOM_LONG_TOKEN'
python3 ~/server_tunnel.py \
  --listen 0.0.0.0 \
  --port 7443 \
  --cert ~/py-tunnel/server.crt \
  --key ~/py-tunnel/server.key
```

### 1.4 Keep running with systemd (optional)

Create `/etc/systemd/system/py-tunnel.service`:

```ini
[Unit]
Description=Python Minimal Tunnel Server
After=network-online.target
Wants=network-online.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu
Environment=TUNNEL_TOKEN=CHANGE_THIS_TO_RANDOM_LONG_TOKEN
ExecStart=/usr/bin/python3 /home/ubuntu/server_tunnel.py --listen 0.0.0.0 --port 7443 --cert /home/ubuntu/py-tunnel/server.crt --key /home/ubuntu/py-tunnel/server.key
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now py-tunnel
sudo systemctl status py-tunnel --no-pager
```

## 2) Client Run (macOS + Windows)

Copy `scripts/tunnel/client_proxy.py` to client machine and run:

```bash
export TUNNEL_TOKEN='CHANGE_THIS_TO_RANDOM_LONG_TOKEN'
python3 client_proxy.py --tunnel 54.169.43.149:7443 --port 7890 --insecure-skip-verify
```

Windows PowerShell:

```powershell
$env:TUNNEL_TOKEN='CHANGE_THIS_TO_RANDOM_LONG_TOKEN'
python .\client_proxy.py --tunnel 54.169.43.149:7443 --port 7890 --insecure-skip-verify
```

`--insecure-skip-verify` is for self-signed cert quick test. For production, use a proper cert and remove this flag.

### 2.1 One Python command: tunnel + PAC together

You can run one script that starts both:

- local CONNECT proxy
- local PAC endpoint

```bash
export TUNNEL_TOKEN='CHANGE_THIS_TO_RANDOM_LONG_TOKEN'
python3 scripts/tunnel/run_client_with_pac.py \
  --tunnel 54.169.43.149:7443 \
  --proxy-port 17890 \
  --pac-port 18080 \
  --insecure-skip-verify
```

Windows PowerShell:

```powershell
$env:TUNNEL_TOKEN='CHANGE_THIS_TO_RANDOM_LONG_TOKEN'
python .\scripts\tunnel\run_client_with_pac.py --tunnel 54.169.43.149:7443 --proxy-port 17890 --pac-port 18080 --insecure-skip-verify
```

PAC URL from this script:

`http://127.0.0.1:18080/proxy.pac`

## 3) System Proxy Setup

## 3.1 macOS

Set Web + Secure Web proxy to `127.0.0.1:7890` for your active network service.

CLI example (`Wi-Fi` service name):

```bash
networksetup -setwebproxy "Wi-Fi" 127.0.0.1 7890
networksetup -setsecurewebproxy "Wi-Fi" 127.0.0.1 7890
networksetup -setwebproxystate "Wi-Fi" on
networksetup -setsecurewebproxystate "Wi-Fi" on
```

Disable:

```bash
networksetup -setwebproxystate "Wi-Fi" off
networksetup -setsecurewebproxystate "Wi-Fi" off
```

## 3.2 Windows

Settings -> Network & Internet -> Proxy -> Manual proxy setup:

- Address: `127.0.0.1`
- Port: `7890`

Or PowerShell:

```powershell
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 1 /f
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer /t REG_SZ /d "127.0.0.1:7890" /f
```

Disable:

```powershell
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 0 /f
```

## 4) Quick Verify

After local proxy running:

```bash
curl -x http://127.0.0.1:7890 -I https://x.com/
curl -x http://127.0.0.1:7890 -I https://chatgpt.com/
```

Expected: successful TLS path, HTTP status may be `200`/`301`/`403` depending on upstream challenge.

## 5) Security Notes

- Keep `TUNNEL_TOKEN` strong and private.
- Keep server allowlist limited (already defaulted to X/OpenAI related suffixes).
- Expose only `7443/TCP` as needed.
- Prefer trusted cert and disable `--insecure-skip-verify` when stable.
