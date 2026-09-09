"""Unit tests part 2: stub_status parse, docker prune safety, postgres tools"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest


class TestNginxStubStatusParsing:
    @pytest.mark.asyncio
    async def test_stub_status_parses_metrics(self):
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_stub_status
        from mcp_linx.types import Status

        body = ("Active connections: 12\n"
                "server accepts handled requests\n"
                " 100 100 250\n"
                "Reading: 0 Writing: 2 Waiting: 10\n")
        resp = httpx.Response(200, text=body, request=httpx.Request("GET", "http://x"))
        plugin = MagicMock(spec=NginxPlugin)
        plugin._config = {"stub_status_url": "http://127.0.0.1/nginx_status"}

        captured: dict = {}

        async def fake_get(url, **kw):
            captured["url"] = url
            return resp

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=fake_get)
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        real_client = httpx.AsyncClient
        httpx.AsyncClient = MagicMock(return_value=mock_cm)
        try:
            result = await nginx_stub_status(plugin, {})
        finally:
            httpx.AsyncClient = real_client

        assert result.status == Status.HEALTHY
        assert result.data["active_connections"] == 12
        assert result.data["requests"] == 250
        assert result.data["waiting"] == 10
        assert captured["url"] == "http://127.0.0.1/nginx_status"


class TestDockerPruneSafety:
    @pytest.mark.asyncio
    async def test_prune_dry_run_default(self):
        from mcp_linx.plugins.docker import DockerPlugin
        from mcp_linx.plugins.docker.tools import docker_prune
        from mcp_linx.types import Status

        plugin = MagicMock(spec=DockerPlugin)
        plugin.list_containers = AsyncMock(return_value=[
            {"id": "a1", "name": "old", "status": "exited", "image": "nginx"},
            {"id": "b2", "name": "web", "status": "running", "image": "app"},
        ])
        result = await docker_prune(plugin, {})
        assert result.status == Status.HEALTHY
        assert result.data["mode"] == "dry-run"
        assert result.data["candidates_count"] == 1
        plugin.list_containers.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_prune_execute_requires_confirm(self):
        from mcp_linx.plugins.docker import DockerPlugin
        from mcp_linx.plugins.docker.tools import docker_prune
        from mcp_linx.types import Status

        plugin = MagicMock(spec=DockerPlugin)
        plugin.prune_containers = AsyncMock()
        result = await docker_prune(plugin, {"execute": True})
        assert result.status == Status.ERROR
        assert "confirm" in result.error_message
        plugin.prune_containers.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_prune_execute_with_confirm(self):
        from mcp_linx.plugins.docker import DockerPlugin
        from mcp_linx.plugins.docker.tools import docker_prune
        from mcp_linx.types import Status

        plugin = MagicMock(spec=DockerPlugin)
        plugin.prune_containers = AsyncMock(
            return_value={"SpaceReclaimed": 100, "ContainersDeleted": ["a1"]}
        )
        result = await docker_prune(plugin, {"execute": True, "confirm": True})
        assert result.status == Status.HEALTHY
        assert result.data["mode"] == "executed"
        plugin.prune_containers.assert_awaited_once()
