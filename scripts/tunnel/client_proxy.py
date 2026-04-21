#!/usr/bin/env python3
"""
Local HTTP CONNECT proxy that tunnels traffic via remote Python tunnel server.

Client app -> localhost:7890 (HTTP CONNECT) -> TLS tunnel -> remote server -> target:443
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import ssl
from urllib.parse import urlsplit


MAGIC = b"PTUNNEL1"


def parse_connect_host_port(target: str) -> tuple[str, int]:
    host, sep, port = target.rpartition(":")
    if not sep:
        raise ValueError("CONNECT target missing port")
    return host.strip(), int(port)


def encode_handshake(token: str, host: str, port: int) -> bytes:
    tb = token.encode("utf-8")
    hb = host.encode("utf-8")
    if len(tb) > 65535 or len(hb) > 65535:
        raise ValueError("token or host too long")
    if port < 1 or port > 65535:
        raise ValueError("invalid port")
    return (
        MAGIC
        + len(tb).to_bytes(2, "big")
        + tb
        + len(hb).to_bytes(2, "big")
        + hb
        + port.to_bytes(2, "big")
    )


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


class LocalProxy:
    def __init__(
        self,
        tunnel_host: str,
        tunnel_port: int,
        token: str,
        insecure_skip_verify: bool,
    ) -> None:
        self.tunnel_host = tunnel_host
        self.tunnel_port = tunnel_port
        self.token = token
        self.insecure_skip_verify = insecure_skip_verify

    async def handle(self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
        peer = client_writer.get_extra_info("peername")
        try:
            req_line = await client_reader.readline()
            if not req_line:
                return
            line = req_line.decode("utf-8", errors="ignore").strip()
            parts = line.split()
            if len(parts) < 3 or parts[0].upper() != "CONNECT":
                client_writer.write(b"HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n")
                await client_writer.drain()
                return
            target = parts[1]
            host, port = parse_connect_host_port(target)

            while True:
                h = await client_reader.readline()
                if not h or h in (b"\r\n", b"\n"):
                    break

            ctx = ssl.create_default_context()
            if self.insecure_skip_verify:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

            tunnel_reader, tunnel_writer = await asyncio.open_connection(
                self.tunnel_host,
                self.tunnel_port,
                ssl=ctx,
                server_hostname=self.tunnel_host if not self.insecure_skip_verify else None,
            )
            tunnel_writer.write(encode_handshake(self.token, host, port))
            await tunnel_writer.drain()
            resp = await tunnel_reader.readexactly(2)
            if resp != b"OK":
                raise ConnectionError("tunnel server rejected target")

            client_writer.write(b"HTTP/1.1 200 Connection Established\r\nProxy-Agent: py-tunnel\r\n\r\n")
            await client_writer.drain()

            t1 = asyncio.create_task(pipe(client_reader, tunnel_writer))
            t2 = asyncio.create_task(pipe(tunnel_reader, client_writer))
            await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
            for t in (t1, t2):
                if not t.done():
                    t.cancel()
        except Exception as exc:
            logging.warning("client %s failed: %s", peer, exc)
            try:
                client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
                await client_writer.drain()
            except Exception:
                pass
        finally:
            try:
                client_writer.close()
                await client_writer.wait_closed()
            except Exception:
                pass


def parse_tunnel(value: str) -> tuple[str, int]:
    if "://" not in value:
        value = "tls://" + value
    u = urlsplit(value)
    if not u.hostname or not u.port:
        raise ValueError("tunnel must be like 54.169.43.149:7443")
    return u.hostname, int(u.port)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Local HTTP CONNECT proxy via Python tunnel")
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7890)
    parser.add_argument("--tunnel", required=True, help="remote tunnel endpoint, e.g. 54.169.43.149:7443")
    parser.add_argument("--token-env", default="TUNNEL_TOKEN")
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
    server = await asyncio.start_server(proxy.handle, host=args.listen, port=args.port)
    sockets = ", ".join(str(s.getsockname()) for s in (server.sockets or []))
    logging.info("local proxy listening on %s", sockets)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
