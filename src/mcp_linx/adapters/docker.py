"""Docker API адаптер для MCP-Linx"""

from __future__ import annotations

import asyncio
from typing import Any

import docker

from mcp_linx.adapters.base import BaseAdapter


class DockerAdapter(BaseAdapter):
    """Адаптер для Docker API"""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._client: docker.DockerClient | None = None
        self._base_url: str = "unix:///var/run/docker.sock"
        self._timeout: int = 10

    async def connect(self) -> None:
        """Установить соединение с Docker"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._connect_sync)

    def _connect_sync(self) -> None:
        """Синхронное подключение"""
        config = self.config
        self._base_url = config.get("host", "unix:///var/run/docker.sock")
        self._timeout = int(config.get("timeout_seconds", 10))

        self._client = docker.DockerClient(base_url=self._base_url, timeout=self._timeout)
        self._client.ping()

    async def disconnect(self) -> None:
        """Закрыть соединение"""
        if self._client:
            self._client.close()
            self._client = None

    async def ping(self) -> bool:
        """Проверка Docker доступности"""
        if not self._client:
            await self.connect()
        try:
            self._client.ping()
            return True
        except Exception:
            return False

    async def list_containers(
        self,
        all_: bool = True,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Список контейнеров"""
        if not self._client:
            await self.connect()

        loop = asyncio.get_event_loop()

        containers = await loop.run_in_executor(
            None,
            lambda: self._client.containers.list(
                all=all_, filters=self._normalize_filters(filters)
            ),
        )

        result = [
            {
                "id": c.id,
                "short_id": c.short_id,
                "name": c.name,
                "status": c.status,
                "image": c.image.tags[0] if c.image.tags else c.image.id,
                "ports": self._format_ports(c.ports),
                "networks": list(c.attrs.get("NetworkSettings", {}).get("Networks", {}).keys()),
                "created": c.attrs.get("Created", ""),
                "command": c.attrs.get("Path", "") + " " + " ".join(c.attrs.get("Args", []) or []),
                "environment": c.attrs.get("Config", {}).get("Env", []),
                "labels": c.attrs.get("Config", {}).get("Labels", {}),
            }
            for c in containers
        ]
        if limit is not None and limit > 0:
            result = result[:limit]
        return result

    @staticmethod
    def _format_ports(ports: Any) -> list[dict[str, Any]]:
        """Нормализовать c.ports (dict) в плоский список."""
        if not ports:
            return []
        if isinstance(ports, list):
            return ports
        result: list[dict[str, Any]] = []
        for container_port, bindings in ports.items():
            if not bindings:
                result.append(
                    {"container_port": container_port, "host_ip": None, "host_port": None}
                )
                continue
            for b in bindings:
                result.append(
                    {
                        "container_port": container_port,
                        "host_ip": b.get("HostIp"),
                        "host_port": b.get("HostPort"),
                    }
                )
        return result

    @staticmethod
    def _normalize_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
        """Docker API ждёт значения-списки: {"status": ["running"]}."""
        if not filters:
            return {}
        normalized: dict[str, Any] = {}
        for k, v in filters.items():
            if isinstance(v, (list, dict)):
                normalized[k] = v
            else:
                normalized[k] = [v]
        return normalized

    async def get_container_logs(
        self,
        container_id: str,
        tail: int = 100,
        since: str | None = None,
    ) -> dict[str, Any]:
        """Получить логи контейнера"""
        if not self._client:
            await self.connect()

        loop = asyncio.get_event_loop()

        container = await loop.run_in_executor(
            None,
            lambda: self._client.containers.get(container_id),
        )

        logs = await loop.run_in_executor(
            None,
            lambda: container.logs(tail=tail, since=since, timestamps=True),
        )

        return {
            "stdout": logs.decode("utf-8", errors="replace") if logs else "",
            "container_id": container_id,
            "tail": tail,
        }

    async def get_container_stats(self, container_id: str) -> dict[str, Any]:
        """Получить статистику контейнера (CPU, memory, network)"""
        if not self._client:
            await self.connect()

        loop = asyncio.get_event_loop()

        container = await loop.run_in_executor(
            None,
            lambda: self._client.containers.get(container_id),
        )

        stats = await loop.run_in_executor(None, lambda: container.stats(stream=False))

        cpu_delta = (
            stats["cpu_stats"]["cpu_usage"]["total_usage"]
            - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        )
        system_delta = (
            stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"]
        )
        cpu_percent = (cpu_delta / system_delta * 100.0) if system_delta > 0 else 0.0

        memory = stats["memory_stats"]
        memory_usage = memory["usage"] - memory.get("cache", 0)
        memory_limit = memory.get("limit", 0)
        memory_percent = (memory_usage / memory_limit * 100.0) if memory_limit > 0 else 0.0

        return {
            "container_id": container_id,
            "cpu_percent": round(cpu_percent, 2),
            "memory_usage_bytes": memory_usage,
            "memory_limit_bytes": memory_limit,
            "memory_percent": round(memory_percent, 2),
            "network": stats.get("networks", {}),
        }

    async def get_container_info(self, container_id: str) -> dict[str, Any]:
        """Полная информация о контейнере (attrs)."""
        if not self._client:
            await self.connect()

        loop = asyncio.get_event_loop()

        def _get() -> dict[str, Any]:
            container = self._client.containers.get(container_id)
            return dict(container.attrs or {})

        return await loop.run_in_executor(None, _get)

    async def get_events(
        self,
        since: str | None = None,
        until: str | None = None,
        event_filters: list[str] | dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Docker events: поток останавливаем после короткого окна, иначе зависнет."""
        if not self._client:
            await self.connect()

        loop = asyncio.get_event_loop()

        if isinstance(event_filters, list):
            filters: dict[str, Any] = {"type": event_filters}
        else:
            filters = dict(event_filters or {})

        def _collect() -> list[dict[str, Any]]:
            kwargs: dict[str, Any] = {"filters": filters, "decode": True}
            if since:
                kwargs["since"] = since
            if until:
                kwargs["until"] = until
            events = []
            # Берём максимум несколько событий чтобы не блокировать executor надолго
            for i, event in enumerate(self._client.events(**kwargs)):
                events.append(event)
                if i >= 19:
                    break
            return events

        try:
            return await asyncio.wait_for(loop.run_in_executor(None, _collect), timeout=15)
        except TimeoutError:
            return []

    async def system_df(self) -> dict[str, Any]:
        """Информация об использовании диска Docker"""
        if not self._client:
            await self.connect()

        loop = asyncio.get_event_loop()

        df = await loop.run_in_executor(None, lambda: self._client.api.df())

        return {
            "Containers": {
                "count": len(df.get("Containers", []) or []),
            },
            "Images": {
                "count": len(df.get("Images", []) or []),
            },
            "Volumes": {
                "count": len(df.get("Volumes", []) or []),
            },
        }

    async def prune_containers(
        self,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Удалить остановленные контейнеры

        Args:
            filters: Фильтры для контейнеров (например, {"status": "exited"})

        Returns:
            Результат удаления: контейнеры, объём освобождённого места
        """
        if not self._client:
            await self.connect()

        loop = asyncio.get_event_loop()

        result = await loop.run_in_executor(
            None,
            lambda: self._client.containers.prune(filters=filters or {}),
        )

        return {
            "SpaceReclaimed": result.get("SpaceReclaimed", 0),
            "ContainersDeleted": result.get("ContainersDeleted", []),
        }
