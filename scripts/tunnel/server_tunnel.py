#!/usr/bin/env python3
"""
Minimal authenticated TCP tunnel server.

Protocol (binary):
  client -> server:
    8 bytes magic: b"PTUNNEL1"
    2 bytes token length (big endian)
    N bytes token (utf-8)
    2 bytes host length (big endian)
    M bytes host (ascii/utf-8)
    2 bytes port (big endian)

If token/target allowed, server connects target and starts raw bidirectional relay.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import ssl
from typing import Iterable


MAGIC = b"PTUNNEL1"


def parse_allowlist(raw: str) -> list[str]:
    items = [x.strip().lower() for x in raw.split(",") if x.strip()]
    if not items:
        raise ValueError("allowlist is empty")
    return items


def is_host_allowed(host: str, allowlist: Iterable[str]) -> bool:
    h = host.lower().strip(".")
    for suffix in allowlist:
        s = suffix.lower().strip(".")
        if h == s or h.endswith("." + s):
            return True
    return False


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


async def read_exact(reader: asyncio.StreamReader, n: int) -> bytes:
    data = await reader.readexactly(n)
    if len(data) != n:
        raise ConnectionError("short read")
    return data


async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    token: str,
    allowlist: list[str],
) -> None:
    peer = writer.get_extra_info("peername")
    try:
        magic = await read_exact(reader, 8)
        if magic != MAGIC:
            raise ValueError("bad magic")

        tok_len = int.from_bytes(await read_exact(reader, 2), "big")
        recv_token = (await read_exact(reader, tok_len)).decode("utf-8", errors="ignore")
        if recv_token != token:
            raise ValueError("bad token")

        host_len = int.from_bytes(await read_exact(reader, 2), "big")
        host = (await read_exact(reader, host_len)).decode("utf-8", errors="ignore").strip()
        port = int.from_bytes(await read_exact(reader, 2), "big")

        if port != 443:
            raise ValueError(f"port {port} not allowed")
        if not is_host_allowed(host, allowlist):
            raise ValueError(f"host {host!r} not allowed")

        try:
            remote_reader, remote_writer = await asyncio.open_connection(host, port)
        except Exception as exc:
            raise ConnectionError(f"upstream connect failed: {exc}") from exc

        writer.write(b"OK")
        await writer.drain()

        t1 = asyncio.create_task(pipe(reader, remote_writer))
        t2 = asyncio.create_task(pipe(remote_reader, writer))
        await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
        for t in (t1, t2):
            if not t.done():
                t.cancel()
    except Exception as exc:
        logging.warning("reject %s: %s", peer, exc)
        try:
            writer.write(b"NO")
            await writer.drain()
        except Exception:
            pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def main() -> None:
    parser = argparse.ArgumentParser(description="Minimal authenticated tunnel server")
    parser.add_argument("--listen", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7443)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument(
        "--allow",
        default=(
            "x.com,twitter.com,t.co,twimg.com,"
            "openai.com,chatgpt.com,oaistatic.com,oaiusercontent.com,"
            "platform.openai.com,featuregates.org,statsig.com,statsigapi.net,"
            "intercom.io,intercomcdn.com,workos.com,workoscdn.com,imgix.net,sendgrid.net,"
            "cursor.sh,github.com,githubusercontent.com,githubassets.com"
        ),
        help="comma-separated allowed suffixes",
    )
    parser.add_argument("--token-env", default="TUNNEL_TOKEN")
    args = parser.parse_args()

    token = os.getenv(args.token_env, "").strip()
    if not token:
        raise SystemExit(f"missing env {args.token_env}")
    allowlist = parse_allowlist(args.allow)

    ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ssl_ctx.load_cert_chain(args.cert, args.key)

    server = await asyncio.start_server(
        lambda r, w: handle_client(r, w, token=token, allowlist=allowlist),
        host=args.listen,
        port=args.port,
        ssl=ssl_ctx,
    )
    sockets = ", ".join(str(s.getsockname()) for s in (server.sockets or []))
    logging.info("server listening on %s", sockets)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
