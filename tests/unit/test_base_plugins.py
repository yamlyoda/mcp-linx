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

    @pytest.mark.asyncio
    async def test_linux_logs_blocks_path_traversal(self):
        """log_type вне allowlist не должен конструировать команду с произвольным путём"""
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_logs
        from mcp_linx.types import Status

        plugin = _make_plugin(LinuxPlugin, {
            "_run_command": {"stdout": "", "stderr": "", "returncode": 0},
        })
        for bad in ("../../etc/shadow", "syslog; cat /etc/passwd", "a/b"):
            result = await linux_logs(plugin, {"log_type": bad})
            assert result.status == Status.ERROR, f"log_type={bad} должен быть заблокирован"
        plugin._run_command.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_linux_logs_allowlisted_type_runs(self):
        """Разрешённый log_type выполняется, команда строится только из allowlist"""
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_logs
        from mcp_linx.types import Status

        captured = {}
        plugin = MagicMock(spec=LinuxPlugin)
        async def fake_run(command, timeout=30):
            captured["command"] = command
            return {"stdout": "line1\n", "stderr": "", "returncode": 0}
        plugin._run_command = fake_run

        result = await linux_logs(plugin, {"log_type": "dpkg.log", "lines": 10})
        assert result.status == Status.HEALTHY
        assert captured["command"] == "tail -n 10 /var/log/dpkg.log"


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
