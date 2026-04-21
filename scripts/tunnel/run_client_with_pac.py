#!/usr/bin/env python3
"""
Run local tunnel proxy and PAC server together in one process.

Usage:
  export TUNNEL_TOKEN='...'
  python3 scripts/tunnel/run_client_with_pac.py --tunnel 54.169.43.149:7443

Recommended full command:
  export TUNNEL_TOKEN='...'
  python3 scripts/tunnel/run_client_with_pac.py \
    --tunnel 54.169.43.149:7443 \
    --proxy-port 17890 \
    --pac-port 18080 \
    --insecure-skip-verify

After startup, PAC URL is:
  http://127.0.0.1:18080/proxy.pac

macOS enable PAC:
  networksetup -setautoproxyurl "Wi-Fi" "http://127.0.0.1:18080/proxy.pac"
  networksetup -setautoproxystate "Wi-Fi" on

Windows PowerShell enable PAC:
  reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" /v AutoConfigURL /t REG_SZ /d "http://127.0.0.1:18080/proxy.pac" /f
  reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" /v ProxyEnable /t REG_DWORD /d 0 /f
"""

from __future__ import annotations

import argparse
import asyncio
import os
from textwrap import dedent

from client_proxy import LocalProxy, parse_tunnel


def build_pac(proxy_host: str, proxy_port: int) -> str:
    return dedent(
        f"""
        function FindProxyForURL(url, host) {{
          host = host.toLowerCase();

          if (dnsDomainIs(host, "x.com") ||
              dnsDomainIs(host, "twitter.com") ||
              dnsDomainIs(host, "t.co") ||
              shExpMatch(host, "*.twimg.com")) {{
            return "PROXY {proxy_host}:{proxy_port}";
          }}

          if (dnsDomainIs(host, "openai.com") ||
              dnsDomainIs(host, "chatgpt.com") ||
              shExpMatch(host, "*.oaistatic.com") ||
              shExpMatch(host, "*.oaiusercontent.com") ||
              dnsDomainIs(host, "platform.openai.com") ||
              shExpMatch(host, "*.featuregates.org") ||
              shExpMatch(host, "*.statsig.com") ||
              shExpMatch(host, "*.statsigapi.net") ||
              shExpMatch(host, "*.intercom.io") ||
              shExpMatch(host, "*.intercomcdn.com") ||
              shExpMatch(host, "*.workos.com") ||
              shExpMatch(host, "*.workoscdn.com") ||
              shExpMatch(host, "*.imgix.net") ||
              shExpMatch(host, "*.sendgrid.net")) {{
            return "PROXY {proxy_host}:{proxy_port}";
          }}

          if (dnsDomainIs(host, "cursor.sh") ||
              shExpMatch(host, "*.cursor.sh") ||
              dnsDomainIs(host, "github.com") ||
              shExpMatch(host, "*.githubusercontent.com") ||
              shExpMatch(host, "*.githubassets.com")) {{
            return "PROXY {proxy_host}:{proxy_port}";
          }}

          return "DIRECT";
        }}
        """
    ).strip() + "\n"


async def handle_pac(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, pac_text: str) -> None:
    try:
        req = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
    except Exception:
        req = b""

    first_line = req.splitlines()[0].decode("utf-8", errors="ignore") if req else ""
    ok = first_line.startswith("GET /proxy.pac ")
    if ok:
        body = pac_text.encode("utf-8")
        headers = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: application/x-ns-proxy-autoconfig\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Cache-Control: no-store\r\n"
            "Connection: close\r\n\r\n"
        ).encode("utf-8")
        writer.write(headers + body)
    else:
        body = b"Not Found\n"
        headers = (
            "HTTP/1.1 404 Not Found\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("utf-8")
        writer.write(headers + body)
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run local tunnel proxy + PAC server")
    parser.add_argument("--tunnel", required=True, help="remote tunnel endpoint, e.g. 54.169.43.149:7443")
    parser.add_argument("--token-env", default="TUNNEL_TOKEN")
    parser.add_argument("--proxy-listen", default="127.0.0.1")
    parser.add_argument("--proxy-port", type=int, default=17890)
    parser.add_argument("--pac-listen", default="127.0.0.1")
    parser.add_argument("--pac-port", type=int, default=18080)
    parser.add_argument("--insecure-skip-verify", action="store_true")
    args = parser.parse_args()

    token = os.getenv(args.token_env, "").strip()
    if not token:
        raise SystemExit(f"missing env {args.token_env}")

    tunnel_host, tunnel_port = parse_tunnel(args.tunnel)
    proxy = LocalProxy(
        tunnel_host=tunnel_host,
        tunnel_port=tunnel_port,
        token=token,
        insecure_skip_verify=args.insecure_skip_verify,
    )
    proxy_server = await asyncio.start_server(proxy.handle, host=args.proxy_listen, port=args.proxy_port)

    pac_text = build_pac(args.proxy_listen, args.proxy_port)
    pac_server = await asyncio.start_server(
        lambda r, w: handle_pac(r, w, pac_text),
        host=args.pac_listen,
        port=args.pac_port,
    )

    pac_url = f"http://{args.pac_listen}:{args.pac_port}/proxy.pac"
    print(f"Tunnel proxy listening: {args.proxy_listen}:{args.proxy_port}")
    print(f"PAC URL: {pac_url}")
    print("Press Ctrl+C to stop.")

    async with proxy_server, pac_server:
        await asyncio.gather(proxy_server.serve_forever(), pac_server.serve_forever())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
