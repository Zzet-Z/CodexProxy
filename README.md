# CloudProxy 项目交接文档

本项目用于把 `x.com`、`ChatGPT/OpenAI`、以及 `Codex/Cursor` 相关流量，稳定地经云机转发，减少客户端直连被策略拦截的问题。

适用人群：不懂运维也能照步骤执行。  
当前日期基线：`2026-04-22`。

## 1. 这个项目解决什么问题

在部分网络环境中，客户端直连 `x.com/chatgpt.com` 会出现 TLS 被重置、握手失败、时好时坏。  
本项目提供两条可用路径：

1. 云机透明代理方案（`nginx stream + mihomo`）
2. 纯 Python 轻量隧道方案（客户端 Windows/macOS 无需安装额外代理软件）

日常建议优先用第 2 条（Python 隧道），因为对客户端最简单。

## 2. 当前涉及的服务器

1. 老机器：`129.204.9.74`（历史方案机器）
2. 新机器：`54.169.43.149`（当前主用）

当前主用入口在 `54.169.43.149`。

## 3. 仓库结构（重点文件）

1. [AGENTS.md](/Users/zzten/AgentProject/CloudProxy/AGENTS.md)
2. [scripts/tunnel/server_tunnel.py](/Users/zzten/AgentProject/CloudProxy/scripts/tunnel/server_tunnel.py)
3. [scripts/tunnel/client_proxy.py](/Users/zzten/AgentProject/CloudProxy/scripts/tunnel/client_proxy.py)
4. [scripts/tunnel/run_client_with_pac.py](/Users/zzten/AgentProject/CloudProxy/scripts/tunnel/run_client_with_pac.py)
5. [docs/operations/2026-04-21-54.169.43.149-x-openai-rollout.md](/Users/zzten/AgentProject/CloudProxy/docs/operations/2026-04-21-54.169.43.149-x-openai-rollout.md)
6. [docs/operations/2026-04-21-python-minimal-tunnel-macos-windows.md](/Users/zzten/AgentProject/CloudProxy/docs/operations/2026-04-21-python-minimal-tunnel-macos-windows.md)

## 4. 两套方案如何选择

1. 你只想快速可用：用 Python 隧道方案。
2. 你需要在云机做统一 SNI 前置与策略路由：用 nginx+mihomo 方案。
3. 客户端是 Windows/macOS 且不想装代理软件：用 Python 隧道 + PAC。

## 5. 方案 A：Python 隧道（推荐）

### 5.1 原理

1. 客户端本地启动一个 HTTP CONNECT 代理（默认 `127.0.0.1:17890`）。
2. 客户端把目标请求封装后，发到云机 `54.169.43.149:7443`（TLS）。
3. 云机 `server_tunnel.py` 验证 token + 域名白名单后，再连接真实目标站点 `443`。
4. PAC 只让指定域名走隧道，其余域名直连。

### 5.2 云机侧当前状态

新机器上已存在并运行：

1. `py-tunnel.service`（systemd）
2. 监听端口：`7443/tcp`
3. 证书：`/home/ubuntu/py-tunnel/server.crt`（当前是自签）
4. token 文件：`/home/ubuntu/py-tunnel/token.env`

检查命令：

```bash
ssh -i ./LightsailDefaultKey-ap-southeast-1.pem ubuntu@54.169.43.149
sudo systemctl status py-tunnel --no-pager
sudo journalctl -u py-tunnel --no-pager -n 100
```

### 5.3 客户端一条命令启动（隧道 + PAC）

macOS:

```bash
cd /Users/zzten/AgentProject/CloudProxy
export TUNNEL_TOKEN='请填当前有效token'
python3 scripts/tunnel/run_client_with_pac.py --tunnel 54.169.43.149:7443 --proxy-port 17890 --pac-port 18080 --insecure-skip-verify
```

Windows PowerShell:

```powershell
cd <你的项目目录>\CloudProxy
$env:TUNNEL_TOKEN='请填当前有效token'
python .\scripts\tunnel\run_client_with_pac.py --tunnel 54.169.43.149:7443 --proxy-port 17890 --pac-port 18080 --insecure-skip-verify
```

PAC 地址固定：

`http://127.0.0.1:18080/proxy.pac`

### 5.4 系统配置 PAC

macOS:

```bash
networksetup -setautoproxyurl "Wi-Fi" "http://127.0.0.1:18080/proxy.pac"
networksetup -setautoproxystate "Wi-Fi" on
```

Windows:

```powershell
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v AutoConfigURL /t REG_SZ /d "http://127.0.0.1:18080/proxy.pac" /f
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 0 /f
```

### 5.5 快速验证

```bash
curl -x http://127.0.0.1:17890 -I https://x.com/
curl -x http://127.0.0.1:17890 -I https://chatgpt.com/
```

Windows 建议用：

```powershell
curl.exe -x http://127.0.0.1:17890 -I https://chatgpt.com/
```

如果出现 `HTTP/1.1 200 Connection Established`，且后续返回 `403/200/301`，通常说明链路是通的。

### 5.6 常见报错

1. `tunnel server rejected target`
- 含义：目标域名不在白名单，或端口不是 443。
- 处理：看云机日志里 `host 'xxx' not allowed`，把对应域名后缀加入 `server_tunnel.py --allow` 或默认 allowlist，重启 `py-tunnel`。

2. 本机访问超时
- 先确认客户端脚本窗口还在运行。
- 再确认云机安全组/防火墙已放通 `7443/tcp`。
- 再测：`openssl s_client -connect 54.169.43.149:7443 -servername 54.169.43.149`。

3. 浏览器仍不走隧道
- 确认 PAC URL 可访问：`http://127.0.0.1:18080/proxy.pac`。
- 重启浏览器。
- 用 `curl.exe -x ...` 先验证代理本身。

## 6. 方案 B：云机 nginx + mihomo（高级）

参考完整落地文档：

1. [2026-04-21-54.169.43.149-x-openai-rollout.md](/Users/zzten/AgentProject/CloudProxy/docs/operations/2026-04-21-54.169.43.149-x-openai-rollout.md)
2. [2026-04-21-sniproxy-mihomo-migration-runbook.md](/Users/zzten/AgentProject/CloudProxy/docs/operations/2026-04-21-sniproxy-mihomo-migration-runbook.md)

关键点：

1. `nginx-xproxy` 读 SNI，前置监听 `443`。
2. `xproxy` 用户流量被 `iptables` 重定向到 `mihomo redir-port`。
3. `mihomo` 负责节点选择与域名规则。
4. 已剔除一批不稳定节点，保留稳定白名单。

## 7. 安全要求（必须遵守）

1. 不要把 `.env`、`.pem`、token 提交到 GitHub。
2. token 泄露后立即轮换：改 `token.env` 并重启 `py-tunnel`。
3. 生产建议替换自签证书，去掉 `--insecure-skip-verify`。
4. 只放行必要端口：`22`、`443`、`7443`（按需）。

## 8. 日常运维最小命令清单

```bash
# 1) 登录新机器
ssh -i ./LightsailDefaultKey-ap-southeast-1.pem ubuntu@54.169.43.149

# 2) 看 Python 隧道状态
sudo systemctl status py-tunnel --no-pager
sudo journalctl -u py-tunnel --no-pager -n 120

# 3) 重启 Python 隧道
sudo systemctl restart py-tunnel

# 4) 看 nginx/mihomo 状态（高级方案）
sudo systemctl status nginx nginx-xproxy mihomo xproxy-iptables --no-pager
```

## 9. 交接清单（给下一任）

1. 确认拿到仓库访问权限。
2. 确认拿到云机 SSH key（`LightsailDefaultKey-ap-southeast-1.pem`）。
3. 确认拿到当前 `TUNNEL_TOKEN`（不要写到仓库）。
4. 本地跑通一次 `run_client_with_pac.py`。
5. 本地验证 `x.com` 与 `chatgpt.com` 可达。
6. 学会看 `py-tunnel` 日志并识别 `host not allowed`。
7. 知道如何扩充白名单并重启服务。

## 10. 版本与变更说明

本仓库已经包含：

1. Python 隧道服务端与客户端脚本。
2. 一键启动（隧道 + PAC）脚本。
3. 旧方案与新方案的完整运维文档。
4. Agent 运行规范与安全边界。

后续新增功能时，请优先更新：

1. `README.md`
2. `docs/operations/*`
3. `AGENTS.md`
