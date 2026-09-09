"""Docker плагин для MCP-Linx"""

from __future__ import annotations

from typing import Any

from mcp_linx.plugins.base import DiagnosticPlugin, PluginTool
from mcp_linx.types import HealthStatus, PluginConfig, Status, ToolResult
from mcp_linx.adapters.docker import DockerAdapter


class DockerPlugin(DiagnosticPlugin):
    """Плагин для диагностики Docker"""

    id = "docker"
    name = "Docker"
    description = "Диагностика Docker: контейнеры, образы, сети, логи, ресурсы"
    version = "1.0.0"

    def __init__(self):
        self._adapter: DockerAdapter | None = None
        self._config: PluginConfig | None = None

    def get_tools(self) -> list[PluginTool]:
        from mcp_linx.plugins.docker.tools import (
            docker_containers,
            docker_logs,
            docker_stats,
            docker_info,
            docker_events,
            docker_system,
            docker_prune,
        )

        return [
            PluginTool("docker_containers", "Список контейнеров с фильтрацией", docker_containers),
            PluginTool("docker_logs", "Логи контейнера", docker_logs),
            PluginTool("docker_stats", "Статистика контейнера: CPU, память, сеть", docker_stats),
            PluginTool("docker_info", "Полная информация о контейнере или системе", docker_info),
            PluginTool("docker_events", "Docker события (контейнеры, образы, сети)", docker_events),
            PluginTool("docker_system_df", "Использование диска Docker", docker_system),
            PluginTool("docker_prune", "Dry-run: список остановленных контейнеров для удаления. Реальное удаление — execute=true, confirm=true", docker_prune),
        ]

    async def initialize(self, config: PluginConfig) -> None:
        self._config = config
        self._adapter = DockerAdapter(config)
        await self._adapter.connect()

    async def health_check(self) -> HealthStatus:
        try:
            ping_result = await self._adapter.ping()
            return HealthStatus(
                Status.HEALTHY if ping_result else Status.UNHEALTHY,
                "Docker is reachable" if ping_result else "Docker is not reachable"
            )
        except Exception as e:
            return HealthStatus(Status.ERROR, f"Health check failed: {e}")

    async def destroy(self) -> None:
        if self._adapter:
            await self._adapter.disconnect()
