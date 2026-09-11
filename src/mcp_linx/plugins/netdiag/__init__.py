"""Netdiag плагин для MCP-Linx"""

from __future__ import annotations

import re
from typing import Any

import httpx

from mcp_linx.adapters.base import BaseAdapter, LocalAdapter
from mcp_linx.adapters.ssh import SSHAdapter
from mcp_linx.plugins.base import DiagnosticPlugin, PluginTool
from mcp_linx.security import SecurityGuard
from mcp_linx.types import HealthStatus, PluginConfig, Status


# Строгий префикс-лист для привилегированных проб (только чтение/сниффинг с лимитами).
# Полные команды дополнительно валидируются в tools (host/user/iface regex, лимиты).
_PRIVILEGED_PREFIXES = (
    "runuser -u ",
    "timeout ",
)


class NetdiagPlugin(DiagnosticPlugin):
    """Плагин сетевой диагностики: HTTP, TLS, DNS, TCP"""

    id = "netdiag"
    name = "Netdiag"
    description = "Сетевая диагностика: HTTP check, TLS expiry, DNS resolve, TCP connect"
    version = "1.0.0"

    def __init__(self):
        self._timeout = 15
        self._adapter: BaseAdapter | None = None
        self._security: SecurityGuard | None = None
        self._config: PluginConfig | None = None

    def get_tools(self) -> list[PluginTool]:
        from mcp_linx.plugins.netdiag.tools import (
            http_check,
            tls_check,
            dns_resolve,
            tcp_connect,
            tcp_connect_as,
            tcpdump_probe,
        )

        return [
            PluginTool("http_check", "HTTP(S) проверка: status, timings, redirects", http_check),
            PluginTool("tls_check", "TLS сертификат: expiry, chain, issuer", tls_check),
            PluginTool("dns_resolve", "DNS резолвинг A/AAAA/CNAME/MX", dns_resolve),
            PluginTool("tcp_connect", "TCP connect к host:port с замером времени", tcp_connect),
            PluginTool("tcp_connect_as", "TCP-проба от имени сервисного пользователя (per-uid фильтры, требует privileged_tools)", tcp_connect_as),
            PluginTool("tcpdump_probe", "Короткий tcpdump-срез host:port (требует privileged_tools)", tcpdump_probe),
        ]

    async def initialize(self, config: PluginConfig) -> None:
        self._config = config
        self._timeout = int(config.get("timeout_seconds", 15))
        ssh_config = config.get("ssh", {})
        host = ssh_config.get("host") if isinstance(ssh_config, dict) else None
        if host:
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
            async with httpx.AsyncClient(timeout=5) as client:
                await client.get("https://example.com")
            return HealthStatus(Status.HEALTHY, "Outbound HTTPS reachable")
        except Exception as e:
            return HealthStatus(Status.DEGRADED, f"Outbound check failed: {e}")

    async def destroy(self) -> None:
        if self._adapter:
            await self._adapter.disconnect()

    async def _run_privileged(self, command: str, timeout: int = 20) -> dict[str, Any]:
        """Выполнение привилегированной пробы со строгим allowlist префиксов.

        Обходит readonly-проверку (runuser/tcpdump не read-only по смыслу),
        но разрешает только команды с известными безопасными префиксами.
        Опасные паттерны (rm -rf и т.д.) проверяются всегда.
        """
        if not self._adapter or not self._security:
            raise RuntimeError("Plugin not initialized")
        stripped = command.strip()
        if not stripped.startswith(_PRIVILEGED_PREFIXES):
            raise RuntimeError(f"Privileged command not allowed: {stripped[:60]}")
        # Проверка опасных паттернов без readonly-ограничения
        for pattern in self._security.DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                from mcp_linx.security import SecurityError
                raise SecurityError(f"Potentially dangerous command blocked: {command[:120]}")
        try:
            result = await self._adapter.execute_command(command, timeout)
            result["stdout"] = self._security.limit_log_lines(result["stdout"])
            return result
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "returncode": 1, "command": command}
