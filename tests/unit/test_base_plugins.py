"""Unit tests for base plugin tools: linux, nginx, docker, postgres"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_plugin(plugin_class, methods: dict):
    plugin = MagicMock(spec=plugin_class)
    for name, ret in methods.items():
        setattr(plugin, name, AsyncMock(return_value=ret))
    return plugin


class TestLinuxTools:
    @pytest.mark.asyncio
    async def test_linux_host_stats_ok(self):
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_host_stats
        from mcp_linx.types import Status

        cmd = {"stdout": "Linux 5.15\n", "stderr": "", "returncode": 0}
        plugin = _make_plugin(LinuxPlugin, {"_run_command": cmd})
        result = await linux_host_stats(plugin, {})
        assert result.status == Status.HEALTHY

    @pytest.mark.asyncio
    async def test_linux_host_stats_cmd_fail_reports_error_in_fields(self):
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_host_stats
        from mcp_linx.types import Status

        plugin = _make_plugin(LinuxPlugin, {
            "_run_command": {"stdout": "", "stderr": "boom", "returncode": 1},
        })
        result = await linux_host_stats(plugin, {})
        # linux_host_stats не падает целиком: ошибки пишутся в поля данных
        assert result.status == Status.HEALTHY
        assert "Error: boom" in result.data["kernel"]


class TestNginxStubStatus:
    @pytest.mark.asyncio
    async def test_stub_status_not_configured(self):
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_stub_status
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NginxPlugin)
        plugin._config = {}
        result = await nginx_stub_status(plugin, {})
        assert result.status == Status.ERROR
        assert "stub_status_url" in result.error_message
