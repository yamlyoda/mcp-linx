"""Systemd плагин для MCP-Linx"""

from __future__ import annotations

from mcp_linx.adapters.base import BaseAdapter, LocalAdapter
from mcp_linx.adapters.ssh import SSHAdapter
from mcp_linx.plugins.base import DiagnosticPlugin, PluginTool
from mcp_linx.security import SecurityGuard
from mcp_linx.types import HealthStatus, PluginConfig, Status


class SystemdPlugin(DiagnosticPlugin):
    """Плагин диагностики systemd: юниты, failed, логи сервиса, boot"""

    id = "systemd"
    name = "Systemd"
    description = "Диагностика systemd: статусы сервисов, failed units, логи, время загрузки"
    version = "1.0.0"

    def __init__(self):
        self._adapter: BaseAdapter | None = None
        self._security: SecurityGuard | None = None

    def get_tools(self) -> list[PluginTool]:
        from mcp_linx.plugins.systemd.tools import (
            service_status,
            failed_units,
            service_logs,
            boot_analysis,
            service_ip_filter,
        )

        return [
            PluginTool("service_status", "Статус systemd юнита (systemctl status/is-active)", service_status),
            PluginTool("failed_units", "Список failed юнитов (systemctl --failed)", failed_units),
            PluginTool("service_logs", "Логи сервиса через journalctl -u", service_logs),
            PluginTool("boot_analysis", "Анализ времени загрузки (systemd-analyze)", boot_analysis),
            PluginTool("service_ip_filter", "Эффективный IP-фильтр юнита: unit-файлы + eBPF/bpftool (ground truth)", service_ip_filter),
        ]

    async def initialize(self, config: PluginConfig) -> None:
        ssh_config = config.get("ssh", {})
        host_ssh = ssh_config.get("host") if isinstance(ssh_config, dict) else None
        if host_ssh:
            self._adapter = SSHAdapter(ssh_config)
        else:
            self._adapter = LocalAdapter({})
        sec = config.get("security", {}) if isinstance(config.get("security"), dict) else {}
        self._security = SecurityGuard({
            "readonly": bool(sec.get("readonly", True)),
            "max_command_output_size": int(sec.get("max_command_output_size", config.get("max_command_output_size", 10000))),
            "max_log_lines": int(sec.get("max_log_lines", config.get("max_log_lines", 200))),
            "command_timeout_seconds": int(sec.get("command_timeout_seconds", config.get("command_timeout_seconds", 15))),
            "allowed_hosts": sec.get("allowed_hosts", ["localhost", "127.0.0.1"]),
        })
        await self._adapter.connect()

    async def health_check(self) -> HealthStatus:
        try:
            result = await self._run("systemctl --version", timeout=10)
            ok = result["returncode"] == 0
            return HealthStatus(
                Status.HEALTHY if ok else Status.UNHEALTHY,
                "systemd available" if ok else "systemd not available",
            )
        except Exception as e:
            return HealthStatus(Status.ERROR, f"Health check failed: {e}")

    async def destroy(self) -> None:
        if self._adapter:
            await self._adapter.disconnect()

    async def _run(self, command: str, timeout: int = 15):
        if not self._adapter or not self._security:
            raise RuntimeError("Plugin not initialized")
        self._security.validate_command(command)
        try:
            result = await self._adapter.execute_command(command, timeout)
            result["stdout"] = self._security.limit_log_lines(result["stdout"])
            return result
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "returncode": 1, "command": command}
