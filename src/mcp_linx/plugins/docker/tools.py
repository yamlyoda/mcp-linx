"""Инструменты Docker плагина"""

from __future__ import annotations

from typing import Any

from mcp_linx.plugins.docker import DockerPlugin
from mcp_linx.types import ToolResult


async def docker_containers(plugin: DockerPlugin, params: dict[str, Any]) -> ToolResult:
    """Список контейнеров с фильтрацией"""
    all_ = params.get("all", True)
    filters = params.get("filters", None)
    
    # Применяем фильтры по умолчанию из конфига
    default_filters = plugin._config.get("filters", {}) if plugin._config else {}
    if filters is None:
        filters = default_filters
    else:
        # Мержим с дефолтом
        merged = dict(default_filters)
        merged.update(filters)
        filters = merged
    
    try:
        containers = await plugin._adapter.list_containers(all_=all_, filters=filters)
        return ToolResult.ok({
            "containers": containers,
            "count": len(containers),
        })
    except Exception as e:
        return ToolResult.error(f"Failed to list containers: {e}")


async def docker_logs(plugin: DockerPlugin, params: dict[str, Any]) -> ToolResult:
    """Логи контейнера"""
    container_id = params.get("container_id")
    tail = int(params.get("tail", 100))
    since = params.get("since")
    
    if not container_id:
        return ToolResult.error("Container ID is required")
    
    try:
        logs = await plugin._adapter.get_container_logs(container_id, tail=tail, since=since)
        return ToolResult.ok({
            "logs": logs["stdout"],
            "container_id": container_id,
            "tail": tail,
        })
    except Exception as e:
        return ToolResult.error(f"Failed to get logs: {e}")


async def docker_stats(plugin: DockerPlugin, params: dict[str, Any]) -> ToolResult:
    """Статистика контейнера: CPU, память, сеть"""
    container_id = params.get("container_id")
    
    if not container_id:
        return ToolResult.error("Container ID is required")
    
    try:
        stats = await plugin._adapter.get_container_stats(container_id)
        return ToolResult.ok(stats)
    except Exception as e:
        return ToolResult.error(f"Failed to get stats: {e}")


async def docker_info(plugin: DockerPlugin, params: dict[str, Any]) -> ToolResult:
    """Полная информация о контейнере или системе"""
    container_id = params.get("container_id")
    
    if container_id:
        try:
            info = await plugin._adapter.get_container_info(container_id)
            return ToolResult.ok({
                "type": "container",
                "container_id": container_id,
                "info": info,
            })
        except Exception as e:
            return ToolResult.error(f"Failed to get container info: {e}")
    else:
        # Docker системная информация
        try:
            # Docker version
            version = await plugin._adapter._client.version()
            # Docker info
            info = await plugin._adapter._client.info()
            
            return ToolResult.ok({
                "type": "system",
                "version": version,
                "info": {
                    "containers": info.get("Containers", 0),
                    "images": info.get("Images", 0),
                    "driver": info.get("Driver", ""),
                    "storage_driver": info.get("Storage Driver", ""),
                    "ncpu": info.get("NCPU", 0),
                    "memory_bytes": info.get("MemTotal", 0),
                    "docker_root_dir": info.get("DockerRootDir", ""),
                    "kernel_version": info.get("KernelVersion", ""),
                    "os_type": info.get("OSType", ""),
                    "operating_system": info.get("OperatingSystem", ""),
                },
            })
        except Exception as e:
            return ToolResult.error(f"Failed to get system info: {e}")


async def docker_events(plugin: DockerPlugin, params: dict[str, Any]) -> ToolResult:
    """Docker события (контейнеры, образы, сети)"""
    since = params.get("since")
    until = params.get("until")
    event_filters = params.get("filters", ["container"])
    
    try:
        events = await plugin._adapter.get_events(
            since=since,
            until=until,
            event_filters=event_filters,
        )
        return ToolResult.ok({
            "events": events,
            "count": len(events),
        })
    except Exception as e:
        return ToolResult.error(f"Failed to get events: {e}")


async def docker_system(plugin: DockerPlugin, params: dict[str, Any]) -> ToolResult:
    """Использование диска Docker"""
    try:
        df = await plugin._adapter.system_df()
        return ToolResult.ok(df)
    except Exception as e:
        return ToolResult.error(f"Failed to get system df: {e}")


async def docker_prune(plugin: DockerPlugin, params: dict[str, Any]) -> ToolResult:
    """Удалить остановленные контейнеры и освободить место
    
    Args:
        filters: Фильтры для контейнеров (по умолчанию {"status": "exited"})
    """
    filters = params.get("filters", {"status": "exited"})
    
    try:
        result = await plugin._adapter.prune_containers(filters=filters)
        return ToolResult.ok(result)
    except Exception as e:
        return ToolResult.error(f"Failed to prune containers: {e}")
