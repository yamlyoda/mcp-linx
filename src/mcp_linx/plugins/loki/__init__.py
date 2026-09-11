"""Loki плагин для MCP-Linx"""

from __future__ import annotations

import httpx

from mcp_linx.plugins.base import DiagnosticPlugin, PluginTool
from mcp_linx.types import HealthStatus, PluginConfig, Status


class LokiPlugin(DiagnosticPlugin):
    """Плагин поиска по логам в Loki: query_range, labels, tail"""

    id = "loki"
    name = "Loki"
    description = "Поиск по централизованным логам Loki: LogQL, labels, tail"
    version = "1.0.0"

    def __init__(self):
        self._base_url = "http://localhost:3100"
        self._timeout = 20
        self._token: str | None = None

    def get_tools(self) -> list[PluginTool]:
        from mcp_linx.plugins.loki.tools import (
            log_labels,
            log_search,
            log_tail,
        )

        return [
            PluginTool("log_search", "LogQL поиск по логам за период", log_search),
            PluginTool("log_labels", "Список label names/values в Loki", log_labels),
            PluginTool("log_tail", "Последние строки по селектору (tail)", log_tail),
        ]

    async def initialize(self, config: PluginConfig) -> None:
        self._base_url = str(config.get("base_url", "http://localhost:3100")).rstrip("/")
        self._timeout = int(config.get("timeout_seconds", 20))
        self._token = config.get("token") or None

    async def health_check(self) -> HealthStatus:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self._base_url}/ready")
            ok = resp.status_code == 200
            return HealthStatus(
                Status.HEALTHY if ok else Status.UNHEALTHY,
                "Loki reachable" if ok else f"HTTP {resp.status_code}",
            )
        except Exception as e:
            return HealthStatus(Status.ERROR, f"Health check failed: {e}")

    async def destroy(self) -> None:
        return None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}
