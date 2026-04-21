# CloudProxy Agent Guide

## Role

In this project, the agent acts as a cloud server operations assistant for `129.204.9.74`.
The main scope is remote operations related to `nginx` and `clash`.
On this host, the Clash-compatible proxy core is currently running as `mihomo`, not `clash.service`.

## Credentials

Read credentials from the local `.env` file before doing any remote work.
Do not hardcode the password in commands, scripts, logs, or replies.
Do not print the password back to the user unless explicitly required.

Expected variables in `.env`:

```dotenv
CLOUD_USER=root
CLOUD_HOST=129.204.9.74
CLOUD_PASSWORD=...
```

Preferred remote login method:

```bash
source .env
sshpass -p "$CLOUD_PASSWORD" ssh -o StrictHostKeyChecking=no "$CLOUD_USER@$CLOUD_HOST"
```

Use `sshpass` for non-interactive remote access in this project.
Do not hardcode credentials outside `.env`.

Additional key-based host used in this project:

- host: `54.169.43.149`
- user: `ubuntu`
- key file: `./LightsailDefaultKey-ap-southeast-1.pem`

Preferred login method for this host:

```bash
ssh -i ./LightsailDefaultKey-ap-southeast-1.pem -o StrictHostKeyChecking=no ubuntu@54.169.43.149
```

Non-interactive connectivity check:

```bash
ssh -i ./LightsailDefaultKey-ap-southeast-1.pem -o StrictHostKeyChecking=no -o BatchMode=yes ubuntu@54.169.43.149 'echo CONNECTED && hostname'
```

The key file should stay in the project root and must not be committed.

## Working Rules

1. Treat this machine as production-like infrastructure.
2. Start by sourcing `.env` and connecting with `sshpass`.
3. For `nginx` changes, inspect current config first, then validate with `nginx -t` before reload/restart.
4. For `clash` changes, inspect the active config and running service first before modifying anything.
5. Check both `clash` and `mihomo` service names because this host currently uses `mihomo`.
6. Prefer safe operations first: status checks, config reads, backups, validation, then reload.
7. Ask for explicit confirmation before destructive or disruptive actions, including:
   - deleting files
   - replacing major configs
   - restarting services that may interrupt traffic
   - changing firewall, routing, or proxy behavior

## Suggested Workflow

1. Read `.env` for `CLOUD_USER`, `CLOUD_HOST`, and `CLOUD_PASSWORD`.
2. Connect with `sshpass -p "$CLOUD_PASSWORD" ssh -o StrictHostKeyChecking=no "$CLOUD_USER@$CLOUD_HOST"`.
3. If the task targets `54.169.43.149`, use `ssh -i ./LightsailDefaultKey-ap-southeast-1.pem -o StrictHostKeyChecking=no ubuntu@54.169.43.149`.
4. If the task targets the new optimized X/OpenAI proxy host on `54.169.43.149`, read [docs/operations/2026-04-21-54.169.43.149-x-openai-rollout.md](/Users/zzten/AgentProject/CloudProxy/docs/operations/2026-04-21-54.169.43.149-x-openai-rollout.md:1) first.
5. If the task is to use a no-extra-software tunnel for macOS/Windows clients, read [docs/operations/2026-04-21-python-minimal-tunnel-macos-windows.md](/Users/zzten/AgentProject/CloudProxy/docs/operations/2026-04-21-python-minimal-tunnel-macos-windows.md:1) first.
6. If the task is to replicate the older `129.204.9.74` stack on another server, read [docs/operations/2026-04-21-sniproxy-mihomo-migration-runbook.md](/Users/zzten/AgentProject/CloudProxy/docs/operations/2026-04-21-sniproxy-mihomo-migration-runbook.md:1) first.
7. Inspect the current `nginx` / `clash` state before editing.
8. Back up important config files before changing them.
9. Validate the updated config.
10. Reload services when validation passes.
11. Report what changed and any remaining risks.

## Common Checks

Typical `nginx` checks:

```bash
nginx -t
systemctl status nginx
journalctl -u nginx --no-pager -n 100
```

Typical `clash` / `mihomo` checks:

```bash
systemctl status clash || systemctl status mihomo
journalctl -u clash --no-pager -n 100 || journalctl -u mihomo --no-pager -n 100
systemctl cat mihomo
sed -n '1,240p' /etc/mihomo/config.yaml
```
