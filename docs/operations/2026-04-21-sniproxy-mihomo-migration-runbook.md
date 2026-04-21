# SNI Proxy Migration Runbook

## Purpose

This document records the full deployment path used on `129.204.9.74` so another agent can reproduce the same X/OpenAI TCP-443 proxy design on a different server.

It covers:

- why the final architecture changed from the original design
- what was changed on the source server
- what to check before repeating the rollout elsewhere
- exact config patterns, validation commands, and rollback order

Use this together with:

- [design](/Users/zzten/AgentProject/CloudProxy/docs/superpowers/specs/2026-04-21-x-openai-split-dns-proxy-design.md:1)
- [implementation plan](/Users/zzten/AgentProject/CloudProxy/docs/superpowers/plans/2026-04-21-x-openai-split-dns-proxy-implementation-plan.md:1)

## Final Architecture

The deployed stack is:

1. client sends HTTPS to the cloud host on `443`
2. `sniproxy` reads TLS SNI and decides whether the request belongs to X/OpenAI
3. matched traffic is forwarded upstream as raw TCP
4. `iptables nat OUTPUT` redirects only `sniproxy` egress into `mihomo redir-port`
5. `mihomo` routes that traffic through the dedicated `X-OPENAI` group
6. unmatched SNI falls back to the local HTTPS site on `127.0.0.1:8443`

This is a TCP layer-4 passthrough design. It does not terminate third-party TLS.

## Why The Architecture Changed

The original design idea was:

- `nginx stream`
- `ssl_preread`
- `redsocks`
- `mihomo SOCKS5`

The real host forced a different implementation:

1. `nginx 1.14.1` had a dynamic `stream` module but did not support `ssl_preread`.
2. `redsocks` was not available from the server package sources.
3. direct DNS for `chatgpt.com` on the host returned polluted answers, so pure hostname passthrough failed.

Because of that, the working solution became:

- `sniproxy` for ingress
- `mihomo redir-port` for transparent TCP egress handoff
- a pinned Cloudflare edge IP for `chatgpt.com`

## Preconditions On A New Server

Before attempting the rollout on another server, check all of these first:

1. `nginx` is present and you know which site currently owns public `443`.
2. `mihomo` or `clash` is already installed and working.
3. you know which user the ingress proxy will run as.
4. the server allows adding `iptables` NAT rules.
5. there is no conflicting service already required on public `443`.
6. you can build software from source if the distro package set is incomplete.

Minimum command set:

```bash
nginx -v
nginx -t
systemctl status nginx --no-pager
systemctl status mihomo --no-pager || systemctl status clash --no-pager
ss -lntp
iptables -t nat -S
```

## Source Server Reference State

The source server `129.204.9.74` ended in this state:

- `sniproxy` owns public `0.0.0.0:443`
- `nginx` site `zzetz.cn` listens on `127.0.0.1:8443`
- `mihomo` listens on:
  - `127.0.0.1:7890`
  - `127.0.0.1:7891`
  - `127.0.0.1:7892`
  - `127.0.0.1:9090`
- `iptables` redirects only `sniproxy` user TCP egress to `7892`
- `X-OPENAI` defaults to `DaWang-US-Xr2`

## Deployment Sequence

Follow this order on a new server.

### 1. Snapshot Everything First

Back up current state before touching routing or listeners.

Suggested commands:

```bash
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p /root/proxy-rollout-backup-$stamp
cp -a /etc/nginx/nginx.conf /root/proxy-rollout-backup-$stamp/ || true
cp -a /etc/nginx/conf.d /root/proxy-rollout-backup-$stamp/ || true
cp -a /etc/mihomo/config.yaml /root/proxy-rollout-backup-$stamp/ || true
nginx -T > /root/proxy-rollout-backup-$stamp/nginx-T.txt 2>&1 || true
systemctl status nginx --no-pager > /root/proxy-rollout-backup-$stamp/nginx-status.txt || true
systemctl status mihomo --no-pager > /root/proxy-rollout-backup-$stamp/mihomo-status.txt || true
iptables -t nat -S > /root/proxy-rollout-backup-$stamp/iptables-nat.txt || true
```

### 2. Move The Existing HTTPS Site Off Public 443

The fallback site must keep working, but it can no longer own public `443`.

Source-server pattern:

- public site moved from `443` to `127.0.0.1:8443`
- public `80` stayed unchanged

Validation:

```bash
nginx -t
systemctl reload nginx
ss -lntp | grep 8443
curl -k -I --resolve your-domain:8443:127.0.0.1 https://your-domain:8443/
```

### 3. Install And Configure `sniproxy`

If the distro does not have a suitable package, build from source.

Source server used:

- `sniproxy 0.7.0`
- installed binary: `/usr/local/sbin/sniproxy`

Reference config:

```conf
user sniproxy
pidfile /run/sniproxy.pid

resolver {
    nameserver 223.5.5.5
    nameserver 223.6.6.6
    mode ipv4_only
}

error_log {
    syslog daemon
    priority notice
}

listener 0.0.0.0:443 {
    protocol tls
    table https_hosts
    fallback 127.0.0.1:8443
}

table https_hosts {
    (^|.*\\.)x\\.com$ *:443
    (^|.*\\.)twitter\\.com$ *:443
    ^t\\.co$ *:443
    (^|.*\\.)twimg\\.com$ *:443
    (^|.*\\.)openai\\.com$ *:443
    (^|.*\\.)chatgpt\\.com$ 104.18.32.47:443
    (^|.*\\.)oaistatic\\.com$ *:443
    (^|.*\\.)oaiusercontent\\.com$ *:443
    (^|.*\\.)featuregates\\.org$ *:443
    (^|.*\\.)statsig\\.com$ *:443
    (^|.*\\.)statsigapi\\.net$ *:443
    (^|.*\\.)intercom\\.io$ *:443
    (^|.*\\.)intercomcdn\\.com$ *:443
    (^|.*\\.)workos\\.com$ *:443
    (^|.*\\.)workoscdn\\.com$ *:443
    (^|.*\\.)imgix\\.net$ *:443
    (^|.*\\.)sendgrid\\.net$ *:443
}
```

Systemd unit used on the source server:

```ini
[Unit]
Description=SNI Proxy Front Door
After=network-online.target nginx.service mihomo.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/sbin/sniproxy -f -c /etc/sniproxy.conf
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
```

Validation:

```bash
systemctl daemon-reload
systemctl enable --now sniproxy
systemctl status sniproxy --no-pager
ss -lntp | grep ':443 '
```

### 4. Redirect Only `sniproxy` Egress Into `mihomo`

The key safety rule is narrow scope: do not transparently capture the whole machine.

Source-server iptables helper:

```sh
#!/bin/sh
set -eu
CHAIN=SNIPROXY_MIHOMO
UID_NAME=sniproxy
PORT=7892

create_chain() {
  iptables -t nat -N "$CHAIN" 2>/dev/null || true
  iptables -t nat -F "$CHAIN"
  iptables -t nat -A "$CHAIN" -d 127.0.0.0/8 -j RETURN
  iptables -t nat -A "$CHAIN" -d 10.0.0.0/8 -j RETURN
  iptables -t nat -A "$CHAIN" -d 172.16.0.0/12 -j RETURN
  iptables -t nat -A "$CHAIN" -d 192.168.0.0/16 -j RETURN
  iptables -t nat -A "$CHAIN" -d 169.254.0.0/16 -j RETURN
  iptables -t nat -A "$CHAIN" -d 100.64.0.0/10 -j RETURN
  iptables -t nat -A "$CHAIN" -p tcp --dport 53 -j RETURN
  iptables -t nat -A "$CHAIN" -p tcp -j REDIRECT --to-ports "$PORT"
  iptables -t nat -C OUTPUT -p tcp -m owner --uid-owner "$UID_NAME" -j "$CHAIN" 2>/dev/null || \
    iptables -t nat -A OUTPUT -p tcp -m owner --uid-owner "$UID_NAME" -j "$CHAIN"
}

delete_chain() {
  iptables -t nat -D OUTPUT -p tcp -m owner --uid-owner "$UID_NAME" -j "$CHAIN" 2>/dev/null || true
  iptables -t nat -F "$CHAIN" 2>/dev/null || true
  iptables -t nat -X "$CHAIN" 2>/dev/null || true
}

case "${1:-}" in
  start) create_chain ;;
  stop) delete_chain ;;
  restart) delete_chain; create_chain ;;
  *) echo "usage: $0 {start|stop|restart}" >&2; exit 1 ;;
esac
```

Systemd wrapper:

```ini
[Unit]
Description=iptables redirect for sniproxy traffic into mihomo redir-port
After=network-online.target mihomo.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/sniproxy-iptables.sh start
ExecStop=/usr/local/sbin/sniproxy-iptables.sh stop
ExecReload=/usr/local/sbin/sniproxy-iptables.sh restart

[Install]
WantedBy=multi-user.target
```

Validation:

```bash
systemctl enable --now sniproxy-iptables
iptables -t nat -S
```

Expected key line:

```bash
-A OUTPUT -p tcp -m owner --uid-owner sniproxy -j SNIPROXY_MIHOMO
```

### 5. Prepare `mihomo`

On the source server, `mihomo` ended up with:

```yaml
port: 7890
socks-port: 7891
redir-port: 7892
allow-lan: false
mode: Rule
external-controller: 127.0.0.1:9090
```

The dedicated groups added were:

```yaml
- name: "X-OPENAI-AUTO"
  type: fallback
  url: "http://www.gstatic.com/generate_204"
  interval: 300
  proxies: [US, JP, SG, KR nodes only]

- name: "X-OPENAI"
  type: select
  proxies: ["DaWang-US-Xr2", "X-OPENAI-AUTO", "...manual candidates..."]
```

The rule block inserted at the top of `rules:` was:

```yaml
- IN-PORT,7892,X-OPENAI
- DOMAIN-SUFFIX,x.com,X-OPENAI
- DOMAIN-SUFFIX,twitter.com,X-OPENAI
- DOMAIN-SUFFIX,t.co,X-OPENAI
- DOMAIN-SUFFIX,twimg.com,X-OPENAI
- DOMAIN-SUFFIX,openai.com,X-OPENAI
- DOMAIN-SUFFIX,chatgpt.com,X-OPENAI
- DOMAIN-SUFFIX,oaistatic.com,X-OPENAI
- DOMAIN-SUFFIX,oaiusercontent.com,X-OPENAI
- DOMAIN-SUFFIX,featuregates.org,X-OPENAI
- DOMAIN-SUFFIX,statsig.com,X-OPENAI
- DOMAIN-SUFFIX,statsigapi.net,X-OPENAI
- DOMAIN-SUFFIX,intercom.io,X-OPENAI
- DOMAIN-SUFFIX,intercomcdn.com,X-OPENAI
- DOMAIN-SUFFIX,workos.com,X-OPENAI
- DOMAIN-SUFFIX,workoscdn.com,X-OPENAI
- DOMAIN-SUFFIX,imgix.net,X-OPENAI
- DOMAIN-SUFFIX,sendgrid.net,X-OPENAI
```

Validation:

```bash
/usr/local/bin/mihomo -t -f /etc/mihomo/config.yaml
systemctl restart mihomo
systemctl status mihomo --no-pager
curl -s http://127.0.0.1:9090/proxies/X-OPENAI
```

## Critical Decision Points

### If `nginx stream` works on the new server

You can still use it, but only if:

- `ssl_preread` is actually available
- `nginx` can do the SNI routing you need

Do not assume because `stream` is present that `ssl_preread` is also available.

Check explicitly:

```bash
nginx -V 2>&1
```

If `ssl_preread` is missing or test configs fail, switch to `sniproxy`.

### If `chatgpt.com` fails but `platform.openai.com` works

Suspect DNS pollution first, not the proxy chain.

Source-server pattern:

1. verify `chatgpt.com` works through `mihomo SOCKS5`
2. verify `chatgpt.com` fails only through `sniproxy`
3. resolve `chatgpt.com` through trusted DoH over `mihomo`
4. pin the `chatgpt.com` rule to a working Cloudflare IP

Reference checks:

```bash
curl --socks5-hostname 127.0.0.1:7891 -I https://chatgpt.com/
curl -I --connect-to chatgpt.com:443:127.0.0.1:443 https://chatgpt.com/
curl --socks5-hostname 127.0.0.1:7891 'https://dns.google/resolve?name=chatgpt.com&type=A'
```

### If `X-OPENAI-AUTO` selects a bad node

Do not insist on auto selection.

On the source server:

- some nodes worked for `x.com` but failed for `chatgpt.com`
- `X-OPENAI` was pinned to `DaWang-US-Xr2`

Selector API:

```bash
curl -X PUT http://127.0.0.1:9090/proxies/X-OPENAI \
  -H 'Content-Type: application/json' \
  -d '{"name":"DaWang-US-Xr2"}'
```

## Validation Checklist

Run these with proxy env vars unset.

### Direct `mihomo` checks

```bash
curl --socks5-hostname 127.0.0.1:7891 -I https://x.com/
curl --socks5-hostname 127.0.0.1:7891 -I https://chatgpt.com/
curl --socks5-hostname 127.0.0.1:7891 -I https://platform.openai.com/
```

### End-to-end front-door checks

```bash
curl -m 20 -I --connect-to x.com:443:127.0.0.1:443 https://x.com/
curl -m 20 -I --connect-to t.co:443:127.0.0.1:443 https://t.co/
curl -m 20 -I --connect-to pbs.twimg.com:443:127.0.0.1:443 https://pbs.twimg.com/
curl -m 20 -I --connect-to chatgpt.com:443:127.0.0.1:443 https://chatgpt.com/
curl -m 20 -I --connect-to desktop.chatgpt.com:443:127.0.0.1:443 https://desktop.chatgpt.com/
curl -m 20 -I --connect-to platform.openai.com:443:127.0.0.1:443 https://platform.openai.com/
curl -m 20 -I --connect-to your-domain:443:127.0.0.1:443 https://your-domain/
```

Expected outcomes:

- `x.com` can return `200` or another valid non-handshake HTTP response
- OpenAI domains may return Cloudflare challenge `403`; that still proves the chain works
- the local site must still answer through fallback

### Service health

```bash
systemctl --no-pager --full status mihomo sniproxy sniproxy-iptables
ss -lntp | grep -E ':443 |:8443 |:7891 |:7892 |:9090 '
iptables -t nat -S
```

## Rollback Order

Use this exact order to reduce blast radius:

1. `systemctl stop sniproxy`
2. `systemctl stop sniproxy-iptables`
3. restore original nginx site config so nginx owns public `443` again
4. `nginx -t && systemctl reload nginx`
5. if needed, restore original `mihomo` config and restart `mihomo`
6. verify public site is back before touching client DNS or `hosts`

## What Not To Do

Do not do these:

- do not terminate TLS for `x.com` or OpenAI domains
- do not expose `mihomo` listeners publicly
- do not capture all machine traffic with a broad transparent proxy rule
- do not assume `chatgpt.com` DNS is trustworthy from the server’s default resolvers
- do not leave `X-OPENAI` on a flaky auto-selected node if validation shows partial failures

## Minimal Copy Checklist For Another Server

Another agent can treat this as the short checklist:

1. back up nginx, mihomo, and NAT state
2. move current HTTPS site from public `443` to `127.0.0.1:8443`
3. install and start `sniproxy`
4. add X/OpenAI SNI allowlist and fallback
5. enable `mihomo redir-port`
6. add `X-OPENAI-AUTO` and `X-OPENAI`
7. add `sniproxy`-only NAT redirect to `7892`
8. validate `x.com`, `chatgpt.com`, `platform.openai.com`, and fallback site
9. if `chatgpt.com` alone fails, test for DNS pollution and pin a working Cloudflare edge IP
10. only after server-side validation, move on to client `hosts` or split DNS
