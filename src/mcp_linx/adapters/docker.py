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
    ) -> list[dict[str, Any]]:
        """Список контейнеров"""
        if not self._client:
            await self.connect()
        
        loop = asyncio.get_event_loop()
        
        containers = await loop.run_in_executor(
            None,
            lambda: self._client.containers.list(all=all_, filters=filters or {}),
        )
        
        return [
            {
                "id": c.id,
                "short_id": c.short_id,
                "name": c.name,
                "status": c.status,
                "image": c.image.tags[0] if c.image.tags else c.image.id,
                "ports": [p["PublicPort"] for p in c.ports] if c.ports else [],
                "networks": list(c.networks.keys()) if c.networks else [],
                "created": c.attrs.get("Created", ""),
                "command": c.attrs.get("Path", "") + " " + " ".join(c.attrs.get("Args", [])),
                "environment": c.attrs.get("Config", {}).get("Env", []),
                "labels": c.attrs.get("Config", {}).get("Labels", {}),
            }
            for c in containers
        ]
    
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
        
        cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        system_delta = stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"]
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
    
    async def system_df(self) -> dict[str, Any]:
        """Информация об использовании диска Docker"""
        if not self._client:
            await self.connect()
        
        loop = asyncio.get_event_loop()
        
        df = await loop.run_in_executor(None, lambda: self._client.system.df())
        
        return {
            "Containers": {
                "count": df.get("Containers", {}).get("Total", 0),
                "size": df.get("Containers", {}).get("Size", "0B"),
            },
            "Images": {
                "count": df.get("Images", {}).get("Total", 0),
                "size": df.get("Images", {}).get("Size", "0B"),
            },
            "Volumes": {
                "count": df.get("Volumes", {}).get("Total", 0),
                "size": df.get("Volumes", {}).get("Size", "0B"),
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
