"""Unit tests для `plugins/docker/tools.py` (волна 14).

Без Docker-демона: `_require_adapter` плагина подменяется, методы адаптера —
`AsyncMock`. Покрываем успешные ветки, обязательные параметры, мерж фильтров
из конфига и ошибки адаптера.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_linx.types import Status


def _plugin(**adapter_methods: Any):
    """DockerPlugin-двойник: `_require_adapter()` возвращает мок адаптера."""
    from mcp_linx.plugins.docker import DockerPlugin

    plugin = MagicMock(spec=DockerPlugin)
    adapter = MagicMock()
    for name, value in adapter_methods.items():
        setattr(adapter, name, AsyncMock(return_value=value))
    plugin._require_adapter = MagicMock(return_value=adapter)
    plugin._config = {}
    return plugin, adapter


class TestDockerContainers:
    @pytest.mark.asyncio
    async def test_lists_containers(self):
        from mcp_linx.plugins.docker.tools import docker_containers

        plugin, _ = _plugin(list_containers=[{"id": "a1", "name": "web"}])
        result = await docker_containers(plugin, {})

        assert result.status == Status.HEALTHY
        assert result.data["count"] == 1
        assert result.data["containers"][0]["id"] == "a1"

    @pytest.mark.asyncio
    async def test_merges_config_filters_with_params(self):
        from mcp_linx.plugins.docker.tools import docker_containers

        plugin, adapter = _plugin(list_containers=[])
        plugin._config = {"filters": {"status": "running"}}
        await docker_containers(plugin, {"filters": {"label": "app=web"}})

        adapter.list_containers.assert_awaited_once_with(
            all_=True, filters={"status": "running", "label": "app=web"}
        )

    @pytest.mark.asyncio
    async def test_adapter_error(self):
        from mcp_linx.plugins.docker.tools import docker_containers

        plugin, adapter = _plugin()
        adapter.list_containers = AsyncMock(side_effect=ConnectionError("no daemon"))
        result = await docker_containers(plugin, {})

        assert result.status == Status.ERROR
        assert "no daemon" in (result.error_message or "")


class TestDockerLogs:
    @pytest.mark.asyncio
    async def test_requires_container_id(self):
        from mcp_linx.plugins.docker.tools import docker_logs

        plugin, _ = _plugin()
        result = await docker_logs(plugin, {})

        assert result.status == Status.ERROR
        assert "container" in (result.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_returns_logs(self):
        from mcp_linx.plugins.docker.tools import docker_logs

        plugin, _ = _plugin(
            get_container_logs={"stdout": "line1\nline2\n", "container_id": "a1", "tail": 50}
        )
        result = await docker_logs(plugin, {"container_id": "a1", "tail": 50})

        assert result.status == Status.HEALTHY
        assert result.data["logs"] == "line1\nline2\n"
        assert result.data["tail"] == 50

    @pytest.mark.asyncio
    async def test_adapter_error(self):
        from mcp_linx.plugins.docker.tools import docker_logs

        plugin, adapter = _plugin()
        adapter.get_container_logs = AsyncMock(side_effect=KeyError("gone"))
        result = await docker_logs(plugin, {"container_id": "a1"})

        assert result.status == Status.ERROR


class TestDockerStats:
    @pytest.mark.asyncio
    async def test_requires_container_id(self):
        from mcp_linx.plugins.docker.tools import docker_stats

        plugin, _ = _plugin()
        result = await docker_stats(plugin, {})

        assert result.status == Status.ERROR

    @pytest.mark.asyncio
    async def test_returns_stats(self):
        from mcp_linx.plugins.docker.tools import docker_stats

        plugin, _ = _plugin(get_container_stats={"cpu_percent": 1.5, "memory_percent": 2.0})
        result = await docker_stats(plugin, {"container_id": "a1"})

        assert result.status == Status.HEALTHY
        assert result.data["cpu_percent"] == 1.5

    @pytest.mark.asyncio
    async def test_adapter_error(self):
        from mcp_linx.plugins.docker.tools import docker_stats

        plugin, adapter = _plugin()
        adapter.get_container_stats = AsyncMock(side_effect=RuntimeError("boom"))
        result = await docker_stats(plugin, {"container_id": "a1"})

        assert result.status == Status.ERROR


class TestDockerInfo:
    @pytest.mark.asyncio
    async def test_container_info(self):
        from mcp_linx.plugins.docker.tools import docker_info

        plugin, _ = _plugin(get_container_info={"name": "web", "state": "running"})
        result = await docker_info(plugin, {"container_id": "a1"})

        assert result.status == Status.HEALTHY
        assert result.data["type"] == "container"
        assert result.data["info"]["name"] == "web"

    @pytest.mark.asyncio
    async def test_container_info_error(self):
        from mcp_linx.plugins.docker.tools import docker_info

        plugin, adapter = _plugin()
        adapter.get_container_info = AsyncMock(side_effect=KeyError("a1"))
        result = await docker_info(plugin, {"container_id": "a1"})

        assert result.status == Status.ERROR

    @pytest.mark.asyncio
    async def test_system_info(self):
        from mcp_linx.plugins.docker.tools import docker_info

        plugin, _ = _plugin()
        client = MagicMock()
        client.version = MagicMock(return_value={"Version": "26.0.0"})
        client.info = MagicMock(
            return_value={"Containers": 3, "Images": 5, "NCPU": 8, "MemTotal": 1 << 30}
        )
        adapter = plugin._require_adapter()
        adapter._ensure_client = AsyncMock(return_value=client)

        result = await docker_info(plugin, {})

        assert result.status == Status.HEALTHY
        assert result.data["type"] == "system"
        assert result.data["info"]["containers"] == 3
        assert result.data["info"]["ncpu"] == 8

    @pytest.mark.asyncio
    async def test_system_info_error(self):
        from mcp_linx.plugins.docker.tools import docker_info

        plugin, _ = _plugin()
        adapter = plugin._require_adapter()
        adapter._ensure_client = AsyncMock(side_effect=ConnectionError("no daemon"))

        result = await docker_info(plugin, {})

        assert result.status == Status.ERROR


class TestDockerEventsAndSystem:
    @pytest.mark.asyncio
    async def test_events_ok(self):
        from mcp_linx.plugins.docker.tools import docker_events

        plugin, _ = _plugin(get_events=[{"Action": "start"}, {"Action": "die"}])
        result = await docker_events(plugin, {})

        assert result.status == Status.HEALTHY
        assert result.data["count"] == 2

    @pytest.mark.asyncio
    async def test_events_error(self):
        from mcp_linx.plugins.docker.tools import docker_events

        plugin, adapter = _plugin()
        adapter.get_events = AsyncMock(side_effect=RuntimeError("boom"))
        result = await docker_events(plugin, {})

        assert result.status == Status.ERROR

    @pytest.mark.asyncio
    async def test_system_df_ok(self):
        from mcp_linx.plugins.docker.tools import docker_system

        plugin, _ = _plugin(system_df={"LayersSize": 1024})
        result = await docker_system(plugin, {})

        assert result.status == Status.HEALTHY
        assert result.data["LayersSize"] == 1024

    @pytest.mark.asyncio
    async def test_system_df_error(self):
        from mcp_linx.plugins.docker.tools import docker_system

        plugin, adapter = _plugin()
        adapter.system_df = AsyncMock(side_effect=RuntimeError("boom"))
        result = await docker_system(plugin, {})

        assert result.status == Status.ERROR
