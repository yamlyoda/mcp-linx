"""Linux плагин для MCP-Linx"""

from __future__ import annotations

from typing import Any

from mcp_linx.plugins.base import DiagnosticPlugin, PluginTool
from mcp_linx.security import SecurityGuard
from mcp_linx.types import HealthStatus, PluginConfig, Status, ToolResult
from mcp_linx.adapters.base import BaseAdapter, LocalAdapter
from mcp_linx.adapters.ssh import SSHAdapter


class LinuxPlugin(DiagnosticPlugin):
    """Плагин для диагностики Linux хоста"""

    id = "linux"
    name = "Linux Host"
    description = "Диагностика Linux хоста: ресурсы, процессы, логи, сеть, диск"
    version = "1.0.0"

    def __init__(self):
        self._adapter: BaseAdapter | None = None
        self._security: SecurityGuard | None = None

    def get_tools(self) -> list[PluginTool]:
        from mcp_linx.plugins.linux.tools import (
            linux_host_stats,
            linux_processes,
            linux_logs,
            linux_network,
            linux_firewall,
            linux_disk,
            linux_memory,
            linux_execute_command,
        )

        return [
            PluginTool("linux_host_stats", "Получение статистики хоста: CPU, память, диск, загрузка", linux_host_stats),
            PluginTool("linux_processes", "Список запущенных процессов с фильтрацией", linux_processes),
            PluginTool("linux_logs", "Чтение системных логов (journalctl, syslog)", linux_logs),
            PluginTool("linux_network", "Сетевые интерфейсы, порты, соединения", linux_network),
            PluginTool("linux_firewall", "Firewall snapshot: nftables + iptables + policy routing (read-only)", linux_firewall),
            PluginTool("linux_disk", "Использование диска и файловых систем", linux_disk),
            PluginTool("linux_memory", "Детальная информация об использовании памяти", linux_memory),
            PluginTool("linux_execute_command", "Выполнение произвольной read-only команды", linux_execute_command),
        ]

    async def initialize(self, config: PluginConfig) -> None:
        ssh_config = config.get("ssh", {})
        host = ssh_config.get("host")

        if host:
            self._adapter = SSHAdapter(ssh_config)
        else:
            self._adapter = LocalAdapter({})

        sec = config.get("security", {}) if isinstance(config.get("security"), dict) else {}

        self._security = SecurityGuard({
            "readonly": bool(sec.get("readonly", True)),
            "max_command_output_size": int(sec.get("max_command_output_size", config.get("max_command_output_size", 10000))),
            "max_log_lines": int(sec.get("max_log_lines", config.get("max_log_lines", 500))),
            "command_timeout_seconds": int(sec.get("command_timeout_seconds", config.get("command_timeout_seconds", 30))),
            "allowed_hosts": sec.get("allowed_hosts", ["localhost", "127.0.0.1"]),
        })

        await self._adapter.connect()

    async def health_check(self) -> HealthStatus:
        try:
            ping_result = await self._adapter.ping()
            return HealthStatus(Status.HEALTHY if ping_result else Status.UNHEALTHY,
                                "Host is reachable" if ping_result else "Host is not reachable")
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
