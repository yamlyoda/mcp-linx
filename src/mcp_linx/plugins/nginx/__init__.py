"""Nginx плагин для MCP-Linx"""

from __future__ import annotations

from typing import Any

from mcp_linx.adapters.base import BaseAdapter, LocalAdapter
from mcp_linx.adapters.ssh import SSHAdapter
from mcp_linx.plugins.base import DiagnosticPlugin, PluginTool
from mcp_linx.security import SecurityGuard
from mcp_linx.types import HealthStatus, PluginConfig, Status
from mcp_linx.types import ToolResult as ToolResult


class NginxPlugin(DiagnosticPlugin):
    """Плагин для диагностики Nginx"""

    id = "nginx"
    name = "Nginx"
    description = "Диагностика Nginx: статус, логи, конфигурация, upstream"
    version = "1.0.0"

    def __init__(self):
        self._adapter: BaseAdapter | None = None
        self._security: SecurityGuard | None = None
        self._config: PluginConfig | None = None

    def get_tools(self) -> list[PluginTool]:
        from mcp_linx.plugins.nginx.tools import (
            nginx_config,
            nginx_logs,
            nginx_status,
            nginx_stub_status,
            nginx_upstream,
        )

        return [
            PluginTool("nginx_status", "Статус службы Nginx и процессов", nginx_status),
            PluginTool("nginx_logs", "Чтение error и access логов Nginx", nginx_logs),
            PluginTool("nginx_config", "Проверка конфигурации Nginx", nginx_config),
            PluginTool("nginx_upstream", "Статус upstream серверов", nginx_upstream),
            PluginTool(
                "nginx_stub_status",
                "HTTP-проверка stub_status: active connections, requests, reading/writing/waiting",
                nginx_stub_status,
            ),
        ]

    async def initialize(self, config: PluginConfig) -> None:
        self._config = config

        ssh_config = config.get("ssh", {})
        host = ssh_config.get("host")

        if host:
            self._adapter = SSHAdapter(ssh_config)
        else:
            self._adapter = LocalAdapter({})

        sec = config.get("security", {}) if isinstance(config.get("security"), dict) else {}

        self._security = SecurityGuard(
            {
                "readonly": bool(sec.get("readonly", True)),
                "max_command_output_size": int(
                    sec.get("max_command_output_size", config.get("max_command_output_size", 10000))
                ),
                "max_log_lines": int(sec.get("max_log_lines", config.get("max_log_lines", 500))),
                "command_timeout_seconds": int(
                    sec.get("command_timeout_seconds", config.get("command_timeout_seconds", 30))
                ),
                "allowed_hosts": sec.get("allowed_hosts", ["localhost", "127.0.0.1"]),
            }
        )

        await self._adapter.connect()

    async def health_check(self) -> HealthStatus:
        try:
            result = await self._adapter.execute_command("nginx -t 2>&1")
            if result["returncode"] == 0:
                return HealthStatus(Status.HEALTHY, "Nginx configuration is valid")
            return HealthStatus(Status.DEGRADED, f"Nginx config test failed: {result['stderr']}")
        except Exception as e:
            return HealthStatus(Status.ERROR, f"Health check failed: {e}")

    async def destroy(self) -> None:
        if self._adapter:
            await self._adapter.disconnect()

    async def _run_command(self, command: str, timeout: int = 30) -> dict[str, Any]:
        if not self._adapter:
            raise RuntimeError("Plugin not initialized")

        self._security.validate_command(command)

        try:
            result = await self._adapter.execute_command(command, timeout)
            result["stdout"] = self._security.limit_log_lines(result["stdout"])
            return result
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "returncode": 1, "command": command}
