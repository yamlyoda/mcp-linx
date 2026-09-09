"""Netdiag плагин для MCP-Linx"""

from __future__ import annotations

import httpx

from mcp_linx.plugins.base import DiagnosticPlugin, PluginTool
from mcp_linx.types import HealthStatus, PluginConfig, Status


class NetdiagPlugin(DiagnosticPlugin):
    """Плагин сетевой диагностики: HTTP, TLS, DNS, TCP"""

    id = "netdiag"
    name = "Netdiag"
    description = "Сетевая диагностика: HTTP check, TLS expiry, DNS resolve, TCP connect"
    version = "1.0.0"

    def __init__(self):
        self._timeout = 15

    def get_tools(self) -> list[PluginTool]:
        from mcp_linx.plugins.netdiag.tools import (
            http_check,
            tls_check,
            dns_resolve,
            tcp_connect,
        )

        return [
            PluginTool("http_check", "HTTP(S) проверка: status, timings, redirects", http_check),
            PluginTool("tls_check", "TLS сертификат: expiry, chain, issuer", tls_check),
            PluginTool("dns_resolve", "DNS резолвинг A/AAAA/CNAME/MX", dns_resolve),
            PluginTool("tcp_connect", "TCP connect к host:port с замером времени", tcp_connect),
        ]

    async def initialize(self, config: PluginConfig) -> None:
        self._timeout = int(config.get("timeout_seconds", 15))

    async def health_check(self) -> HealthStatus:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.get("https://example.com")
            return HealthStatus(Status.HEALTHY, "Outbound HTTPS reachable")
        except Exception as e:
            return HealthStatus(Status.DEGRADED, f"Outbound check failed: {e}")

    async def destroy(self) -> None:
        return None
