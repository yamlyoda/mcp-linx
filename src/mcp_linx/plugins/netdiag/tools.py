"""Tools netdiag плагина: http, tls, dns, tcp"""

from __future__ import annotations

import asyncio
import socket
import ssl
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from mcp_linx.types import Status, ToolResult


async def http_check(plugin, params: dict[str, Any]) -> ToolResult:
    """HTTP(S) проверка URL: код, время, редиректы"""
    url = str(params.get("url", "")).strip()
    if not url or not url.startswith(("http://", "https://")):
        return ToolResult.error("Param 'url' must start with http:// or https://")
    try:
        timeout = max(2, min(int(params.get("timeout", 15)), 60))
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)
        data = {
            "url": url,
            "final_url": str(resp.url),
            "status_code": resp.status_code,
            "elapsed_ms": elapsed_ms,
            "server": resp.headers.get("server", ""),
            "content_type": resp.headers.get("content-type", ""),
            "content_length": resp.headers.get("content-length", ""),
        }
        if resp.status_code >= 500:
            return ToolResult.degraded(data, [f"Server error {resp.status_code} — см. nginx_logs/docker_logs"])
        if resp.status_code >= 400:
            return ToolResult.degraded(data, [f"Client error {resp.status_code}"])
        if elapsed_ms > 3000:
            return ToolResult.degraded(data, [f"Slow response {elapsed_ms}ms — проверьте upstream/DB"])
        return ToolResult.ok(data)
    except Exception as e:
        return ToolResult.error(str(e))


async def tls_check(plugin, params: dict[str, Any]) -> ToolResult:
    """TLS сертификат хоста: срок, issuer, chain"""
    host = str(params.get("host", "")).strip()
    if not host:
        return ToolResult.error("Param 'host' is required")
    try:
        port = max(1, min(int(params.get("port", 443)), 65535))
        timeout = max(2, min(int(params.get("timeout", 15)), 60))
        ctx = ssl.create_default_context()
        loop = asyncio.get_event_loop()

        def _fetch():
            with socket.create_connection((host, port), timeout=timeout) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                    cert = ssock.getpeercert()
                    chain = ssock.getpeercertchain() if hasattr(ssock, "getpeercertchain") else None
                    return cert, len(chain) if chain else 1

        cert, chain_len = await loop.run_in_executor(None, _fetch)
        not_after = cert.get("notAfter", "")
        dt = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        days_left = (dt - datetime.now(timezone.utc)).days
        issuer = " / ".join("=".join(x[0]) for x in cert.get("issuer", ()))
        subject = " / ".join("=".join(x[0]) for x in cert.get("subject", ()))
        sans = cert.get("subjectAltName", ())
        data = {
            "host": host,
            "port": port,
            "subject": subject,
            "issuer": issuer,
            "not_after": not_after,
            "days_left": days_left,
            "chain_length": chain_len,
            "san": [v for _, v in sans],
        }
        if days_left < 0:
            return ToolResult(status=Status.CRITICAL, data=data,
                              suggestions=["Сертификат ПРОСРОЧЕН — обновите немедленно"])
        if days_left < 14:
            return ToolResult.degraded(data, [f"Сертификат истекает через {days_left} дн."])
        return ToolResult.ok(data)
    except Exception as e:
        return ToolResult.error(str(e))


async def dns_resolve(plugin, params: dict[str, Any]) -> ToolResult:
    """DNS резолвинг имени через socket"""
    name = str(params.get("name", "")).strip()
    if not name:
        return ToolResult.error("Param 'name' is required")
    try:
        loop = asyncio.get_event_loop()

        def _resolve():
            infos = socket.getaddrinfo(name, None)
            v4 = sorted({i[4][0] for i in infos if i[0] == socket.AF_INET})
            v6 = sorted({i[4][0] for i in infos if i[0] == socket.AF_INET6})
            return v4, v6

        v4, v6 = await loop.run_in_executor(None, _resolve)
        data = {"name": name, "a": v4, "aaaa": v6}
        if not v4 and not v6:
            return ToolResult.degraded(data, [f"Имя {name} не резолвится"])
        return ToolResult.ok(data)
    except Exception as e:
        return ToolResult.error(f"DNS resolve failed for '{name}': {e}")


async def tcp_connect(plugin, params: dict[str, Any]) -> ToolResult:
    """TCP connect к host:port"""
    host = str(params.get("host", "")).strip()
    if not host:
        return ToolResult.error("Param 'host' is required")
    try:
        port = max(1, min(int(params.get("port", 80)), 65535))
        timeout = max(1, min(int(params.get("timeout", 10)), 30))
        started = time.monotonic()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return ToolResult.ok({"host": host, "port": port, "reachable": True, "connect_ms": elapsed_ms})
    except Exception as e:
        return ToolResult(
            status=Status.UNHEALTHY,
            data={"host": host, "port": port, "reachable": False},
            error_message=str(e)[:500],
        )
