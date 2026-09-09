"""Prometheus плагин для MCP-Linx"""

from __future__ import annotations

import httpx

from mcp_linx.plugins.base import DiagnosticPlugin, PluginTool
from mcp_linx.types import HealthStatus, PluginConfig, Status


class PrometheusPlugin(DiagnosticPlugin):
    """Плагин запросов к Prometheus: instant/range query, alerts, targets"""

    id = "prometheus"
    name = "Prometheus"
    description = "Запросы к Prometheus API: query, range, alerts, targets"
    version = "1.0.0"

    def __init__(self):
        self._base_url = "http://localhost:9090"
        self._timeout = 20
        self._token: str | None = None

    def get_tools(self) -> list[PluginTool]:
        from mcp_linx.plugins.prometheus.tools import (
            prom_query,
            prom_range,
            prom_alerts,
            prom_targets,
        )

        return [
            PluginTool("prom_query", "Instant query (PromQL) к Prometheus", prom_query),
            PluginTool("prom_range", "Range query за период (графики/история)", prom_range),
            PluginTool("prom_alerts", "Активные алерты (firing/pending)", prom_alerts),
            PluginTool("prom_targets", "Статус scrape targets (up/down)", prom_targets),
        ]

    async def initialize(self, config: PluginConfig) -> None:
        self._base_url = str(config.get("base_url", "http://localhost:9090")).rstrip("/")
        self._timeout = int(config.get("timeout_seconds", 20))
        self._token = config.get("token") or None

    async def health_check(self) -> HealthStatus:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self._base_url}/-/healthy")
            ok = resp.status_code == 200
            return HealthStatus(
                Status.HEALTHY if ok else Status.UNHEALTHY,
                "Prometheus reachable" if ok else f"HTTP {resp.status_code}",
            )
        except Exception as e:
            return HealthStatus(Status.ERROR, f"Health check failed: {e}")

    async def destroy(self) -> None:
        return None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}
