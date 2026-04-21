# X / OpenAI Split-DNS Proxy Implementation Plan

> **For agentic workers:** use `executing-plans` or `subagent-driven-development`.

## Goal

Build a minimal TCP-443-only proxy path on `129.204.9.74` for `X` and `OpenAI/Codex` traffic, keep `zzetz.cn` online, and leave client rollout to split DNS on macOS / Windows.

## Actual Implementation Chosen

The original plan assumed `nginx stream + redsocks`. The real host required a different path:

- ingress: `sniproxy`
- fallback site: `nginx` on `127.0.0.1:8443`
- transparent egress handoff: `iptables nat OUTPUT` for the `sniproxy` user only
- proxy core: `mihomo redir-port` on `127.0.0.1:7892`

Why:

- installed `nginx 1.14.1` lacked usable `ssl_preread`
- `redsocks` was not available from the server package sources
- `chatgpt.com` direct DNS was polluted and needed a pinned Cloudflare edge IP inside `sniproxy`

## Remote File / Service Inventory

- `/etc/sniproxy.conf`
- `/etc/systemd/system/sniproxy.service`
- `/usr/local/sbin/sniproxy-iptables.sh`
- `/etc/systemd/system/sniproxy-iptables.service`
- `/etc/nginx/conf.d/zzetz.cn.conf`
- `/etc/mihomo/config.yaml`
- `sniproxy.service`
- `sniproxy-iptables.service`
- `mihomo.service`

## Execution Status

### Task 1: Snapshot And Back Up Current Server State

- [x] Captured nginx, mihomo, and iptables state
- [x] Created remote backup directory
- [x] Saved timestamped backups before rollout

Notes:

- primary backup directory: `/root/proxy-rollout-backup-20260421-114230`
- additional per-file backups were created during later fixes

### Task 2: Move Existing HTTPS Site Behind Local Port

- [x] Changed `zzetz.cn` HTTPS listener from public `443` to `127.0.0.1:8443`
- [x] Kept existing site logic and certificates unchanged
- [x] Left public `80` behavior intact

Validation:

- [x] `nginx -t`
- [x] `zzetz.cn` over public `443` still returns the local site through `sniproxy` fallback

### Task 3: Add Public SNI Front Door

- [x] Built and installed `sniproxy 0.7.0`
- [x] Added `/etc/sniproxy.conf`
- [x] Added `sniproxy.service`
- [x] Bound public `0.0.0.0:443` to `sniproxy`
- [x] Configured fallback to `127.0.0.1:8443`
- [x] Added X/OpenAI suffix allowlist

Validation:

- [x] `ss -lntp` shows `sniproxy` on public `:443`
- [x] `openssl s_client` / `curl --connect-to` confirmed SNI routing for `x.com`
- [x] unmatched SNI still falls back to `zzetz.cn`

### Task 4: Add Narrow Egress Redirect

- [x] Added `sniproxy`-only NAT chain
- [x] Excluded loopback and private ranges
- [x] Redirected remaining `sniproxy` TCP egress to `127.0.0.1:7892`
- [x] Added `sniproxy-iptables.service` for replay on boot

Validation:

- [x] `iptables -t nat -S` shows `OUTPUT -p tcp -m owner --uid-owner 992 -j SNIPROXY_MIHOMO`
- [x] fallback site traffic remains healthy

### Task 5: Add Dedicated Mihomo Groups And Rules

- [x] Enabled `redir-port: 7892`
- [x] Added `X-OPENAI-AUTO`
- [x] Added `X-OPENAI`
- [x] Added X/OpenAI domain-suffix rules
- [x] Limited the group to US / JP / SG / KR nodes

Current default:

- [x] `X-OPENAI` selector is pinned to `DaWang-US-Xr2`

Reason:

- `X-OPENAI-AUTO` could select nodes that worked for `x.com` but not for `chatgpt.com`

### Task 6: Fix ChatGPT DNS Constraint

- [x] Identified polluted direct DNS answers for `chatgpt.com`
- [x] Verified `chatgpt.com` was healthy through `mihomo SOCKS5`
- [x] Pinned `(^|.*\\.)chatgpt\\.com$` in `/etc/sniproxy.conf` to `104.18.32.47:443`

Validation:

- [x] `chatgpt.com` through the public `443` front door now returns a valid HTTPS response
- [x] `desktop.chatgpt.com` through the same front door also returns a valid HTTPS response

### Task 7: Server-Side Validation

- [x] `x.com` through front door works
- [x] `chatgpt.com` through front door works
- [x] `desktop.chatgpt.com` through front door works
- [x] `platform.openai.com` through front door works
- [x] `zzetz.cn` through front door still reaches the local site
- [x] `mihomo.service` healthy
- [x] `sniproxy.service` healthy
- [x] `sniproxy-iptables.service` healthy

Expected response class:

- `x.com` may return `200` or another valid HTTPS response
- `chatgpt.com` and `platform.openai.com` often return Cloudflare challenge `403`
- these are acceptable connectivity proofs for server-side validation

### Task 8: Client Split DNS Rollout

- [ ] macOS split DNS config not yet applied from this repo session
- [ ] Windows split DNS config not yet applied from this repo session

Needed next:

- point selected suffix groups to `129.204.9.74`
- keep unrelated DNS unchanged

### Task 9: End-To-End Client Validation

- [ ] not yet run from a real macOS or Windows client in this session

Needed next:

- validate `x.com`
- validate `chatgpt.com`
- validate `platform.openai.com`
- validate `t.co` / `pbs.twimg.com`

## Rollback Notes

Fast rollback order:

1. stop `sniproxy.service`
2. stop `sniproxy-iptables.service` and remove `SNIPROXY_MIHOMO` NAT rules
3. restore `/etc/nginx/conf.d/zzetz.cn.conf` from backup so nginx owns public `443` again
4. reload `nginx`
5. restore `/etc/mihomo/config.yaml` backup if needed and restart `mihomo`

Important backup artifacts:

- `/root/proxy-rollout-backup-20260421-114230`
- `/etc/sniproxy.conf.bak.*`
- `/etc/mihomo/config.yaml.bak.*`

## Fresh Validation Commands

Run on the cloud host with proxy env vars unset:

```bash
curl -s http://127.0.0.1:9090/proxies/X-OPENAI
curl -m 20 -I --connect-to x.com:443:127.0.0.1:443 https://x.com/
curl -m 20 -I --connect-to chatgpt.com:443:127.0.0.1:443 https://chatgpt.com/
curl -m 20 -I --connect-to desktop.chatgpt.com:443:127.0.0.1:443 https://desktop.chatgpt.com/
curl -m 20 -I --connect-to platform.openai.com:443:127.0.0.1:443 https://platform.openai.com/
curl -m 20 -I --connect-to zzetz.cn:443:127.0.0.1:443 https://zzetz.cn/
systemctl --no-pager --full status mihomo sniproxy sniproxy-iptables
iptables -t nat -S
```

## Notes For The Next Operator

- Do not terminate TLS for third-party domains.
- Do not expose `mihomo` listeners publicly.
- Keep the SNI allowlist narrow; do not turn this into an open proxy.
- Treat the `chatgpt.com` pinned edge IP as an operational workaround, not a permanent truth.
- Client split DNS remains the only missing rollout step.
