"""Multi-host: реестр целевых хостов из секции `hosts:` конфига.

Позволяет одному инстансу MCP-сервера диагностировать несколько машин:
инструменты linux/nginx/systemd принимают параметр `host` — имя хоста
из реестра; команды выполняются по SSH через пул соединений.
"""

from __future__ import annotations

from typing import Any

from mcp_linx.adapters.ssh_pool import RemoteHostAdapter, SSHConnectionPool


class HostRegistry:
    """Реестр хостов: имя -> RemoteHostAdapter (создаётся лениво, кэшируется)."""

    def __init__(self, config: dict[str, Any], pool: SSHConnectionPool | None = None):
        hosts_cfg = config.get("hosts") if isinstance(config, dict) else None
        self._hosts: dict[str, dict[str, Any]] = (
            dict(hosts_cfg) if isinstance(hosts_cfg, dict) else {}
        )
        self._pool = pool if pool is not None else SSHConnectionPool()
        self._adapters: dict[str, RemoteHostAdapter] = {}

    def list_hosts(self) -> list[str]:
        """Имена всех настроенных хостов (для подсказок при ошибках)."""
        return sorted(self._hosts)

    def has_host(self, name: str) -> bool:
        return name in self._hosts

    def get_adapter(self, name: str) -> RemoteHostAdapter:
        """Адаптер для хоста по имени; KeyError с списком доступных, если нет."""
        if name not in self._hosts:
            available = ", ".join(self.list_hosts()) or "<none configured>"
            raise KeyError(f"Unknown host '{name}'. Configured hosts: {available}")
        adapter = self._adapters.get(name)
        if adapter is None:
            adapter = RemoteHostAdapter(self._pool, self._hosts[name])
            self._adapters[name] = adapter
        return adapter

    def close_all(self) -> None:
        """Закрыть все SSH-соединения пула."""
        self._pool.close_all()
