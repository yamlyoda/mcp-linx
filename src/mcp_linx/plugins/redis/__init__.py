"""Redis плагин для MCP-Linx"""

from __future__ import annotations

from typing import Any

from mcp_linx.adapters.base import BaseAdapter, LocalAdapter
from mcp_linx.adapters.ssh import SSHAdapter
from mcp_linx.plugins.base import DiagnosticPlugin, PluginTool
from mcp_linx.security import SecurityGuard
from mcp_linx.types import HealthStatus, PluginConfig, Status


class RedisPlugin(DiagnosticPlugin):
    """Плагин диагностики Redis: память, клиенты, slowlog, доступность"""

    id = "redis"
    name = "Redis"
    description = "Диагностика Redis: ping, info, clients, slowlog, memory"
    version = "1.0.0"

    def __init__(self):
        self._adapter: BaseAdapter | None = None
        self._security: SecurityGuard | None = None
        self._host = "localhost"
        self._port = 6379
        self._password: str | None = None

    def get_tools(self) -> list[PluginTool]:
        from mcp_linx.plugins.redis.tools import (
            redis_ping,
            redis_info,
            redis_clients,
            redis_slowlog,
            redis_memory,
        )

        return [
            PluginTool("redis_ping", "Проверка доступности Redis (PING)", redis_ping),
            PluginTool("redis_info", "Секции INFO: memory, clients, stats, replication", redis_info),
            PluginTool("redis_clients", "Список клиентских подключений (CLIENT LIST)", redis_clients),
            PluginTool("redis_slowlog", "Slow log Redis (SLOWLOG GET)", redis_slowlog),
            PluginTool("redis_memory", "Анализ памяти: used, peak, fragmentation, evictions", redis_memory),
        ]

    async def initialize(self, config: PluginConfig) -> None:
        ssh_config = config.get("ssh", {})
        host_ssh = ssh_config.get("host") if isinstance(ssh_config, dict) else None
        self._host = str(config.get("host", "localhost"))
        self._port = int(config.get("port", 6379))
        self._password = config.get("password") or None
        if host_ssh:
            self._adapter = SSHAdapter(ssh_config)
        else:
            self._adapter = LocalAdapter({})
        self._security = SecurityGuard({
            "readonly": True,
            "max_command_output_size": int(config.get("max_command_output_size", 10000)),
            "max_log_lines": int(config.get("max_log_lines", 200)),
            "command_timeout_seconds": int(config.get("command_timeout_seconds", 15)),
        })
        await self._adapter.connect()

    async def health_check(self) -> HealthStatus:
        try:
            result = await self._run_redis_cli("PING", timeout=10)
            ok = result["returncode"] == 0 and "PONG" in result["stdout"]
            return HealthStatus(
                Status.HEALTHY if ok else Status.UNHEALTHY,
                "Redis is reachable" if ok else f"Redis not reachable: {result['stderr'][:200]}",
            )
        except Exception as e:
            return HealthStatus(Status.ERROR, f"Health check failed: {e}")

    async def destroy(self) -> None:
        if self._adapter:
            await self._adapter.disconnect()

    def _base_args(self) -> str:
        import shlex

        parts = ["redis-cli", "-h", shlex.quote(self._host), "-p", str(self._port)]
        if self._password:
            parts += ["-a", shlex.quote(self._password)]
        return " ".join(parts)

    async def _run_redis_cli(self, args: str, timeout: int = 15) -> dict[str, Any]:
        if not self._adapter or not self._security:
            raise RuntimeError("Plugin not initialized")
        command = f"{self._base_args()} {args}"
        self._security.validate_command(command)
        try:
            result = await self._adapter.execute_command(command, timeout)
            result["stdout"] = self._security.limit_log_lines(result["stdout"])
            return result
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "returncode": 1, "command": command}
