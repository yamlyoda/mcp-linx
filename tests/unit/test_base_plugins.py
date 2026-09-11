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

        plugin = _make_plugin(
            LinuxPlugin,
            {
                "_run_command": {"stdout": "", "stderr": "boom", "returncode": 1},
            },
        )
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

        plugin = _make_plugin(
            LinuxPlugin,
            {
                "_run_command": {"stdout": "", "stderr": "", "returncode": 0},
            },
        )
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


class TestNginxLogs:
    @pytest.mark.asyncio
    async def test_nginx_logs_blocks_malicious_log_path(self):
        """config_path вне allowlist должен быть заблокирован"""
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_logs
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NginxPlugin)
        plugin._config = {"log_path": "/etc"}
        result = await nginx_logs(plugin, {"log_type": "error"})
        assert result.status == Status.ERROR
        assert "Invalid log_path" in result.error_message

    @pytest.mark.asyncio
    async def test_nginx_logs_blocks_path_traversal_in_filename(self):
        """access_log с '..' или '/' должен быть заблокирован"""
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_logs
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NginxPlugin)
        plugin._config = {"access_log": "../../../etc/passwd"}
        result = await nginx_logs(plugin, {"log_type": "access"})
        assert result.status == Status.ERROR
        assert "Invalid access_log" in result.error_message

    @pytest.mark.asyncio
    async def test_nginx_logs_valid_config_runs(self):
        """Разрешённый config_path и имя файла выполняют команду"""
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_logs
        from mcp_linx.types import Status

        captured = {}
        plugin = MagicMock(spec=NginxPlugin)
        plugin._config = {"log_path": "/var/log/nginx", "error_log": "error.log"}

        async def fake_run(command, timeout=30):
            captured["command"] = command
            return {"stdout": "error log line\n", "stderr": "", "returncode": 0}

        plugin._run_command = fake_run
        result = await nginx_logs(plugin, {"log_type": "error", "lines": 50})
        assert result.status == Status.HEALTHY
        assert captured["command"] == "tail -n 50 /var/log/nginx/error.log"


class TestNginxUpstream:
    @pytest.mark.asyncio
    async def test_upstream_all_healthy(self):
        """Все upstream серверы доступны — status ok"""
        from unittest.mock import AsyncMock

        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_upstream
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NginxPlugin)
        plugin._run_command = AsyncMock(
            return_value={
                "stdout": "upstream backend {\n    server 127.0.0.1:8080;\n    server 127.0.0.1:8081;\n}\n",
                "stderr": "",
                "returncode": 0,
            }
        )

        mock_resp = AsyncMock()
        mock_resp.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)

        import unittest.mock as um

        with um.patch("httpx.AsyncClient", return_value=mock_client):
            result = await nginx_upstream(plugin, {})

        assert result.status == Status.HEALTHY
        assert result.data["live_servers"] == ["127.0.0.1:8080", "127.0.0.1:8081"]
        assert result.data["dead_servers"] == []

    @pytest.mark.asyncio
    async def test_upstream_with_dead_server(self):
        """Один из upstream недоступен — status degraded"""
        from unittest.mock import AsyncMock

        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_upstream
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NginxPlugin)
        plugin._run_command = AsyncMock(
            return_value={
                "stdout": "upstream backend {\n    server 127.0.0.1:8080;\n    server 127.0.0.1:9999;\n}\n",
                "stderr": "",
                "returncode": 0,
            }
        )

        mock_resp_ok = AsyncMock()
        mock_resp_ok.status_code = 200

        mock_resp_fail = AsyncMock()
        mock_resp_fail.status_code = 502

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=[mock_resp_ok, mock_resp_fail])

        import unittest.mock as um

        with um.patch("httpx.AsyncClient", return_value=mock_client):
            result = await nginx_upstream(plugin, {})

        assert result.status == Status.DEGRADED
        assert "127.0.0.1:8080" in result.data["live_servers"]
        assert "127.0.0.1:9999" in result.data["dead_servers"]

    @pytest.mark.asyncio
    async def test_upstream_unix_socket_skipped(self):
        """unix-socket upstream пропускается (недоступен по HTTP)"""
        from unittest.mock import AsyncMock

        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_upstream
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NginxPlugin)
        plugin._run_command = AsyncMock(
            return_value={
                "stdout": "upstream backend {\n    server unix:/tmp/backend.sock;\n}\n",
                "stderr": "",
                "returncode": 0,
            }
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock()

        import unittest.mock as um

        with um.patch("httpx.AsyncClient", return_value=mock_client):
            result = await nginx_upstream(plugin, {})

        assert result.status == Status.HEALTHY
        assert result.data["live_servers"] == []
        mock_client.get.assert_not_called()


class TestNginxConfig:
    @pytest.mark.asyncio
    async def test_nginx_config_ok(self):
        """Конфигурация валидна (returncode=0)"""
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_config
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NginxPlugin)
        plugin._run_command = AsyncMock(
            side_effect=[
                {
                    "stdout": "nginx: configuration file test is successful\n",
                    "stderr": "",
                    "returncode": 0,
                },
                {"stdout": "worker_processes auto;\n", "stderr": "", "returncode": 0},
                {"stdout": "sites-enabled/default\n", "stderr": "", "returncode": 0},
                {"stdout": "", "stderr": "", "returncode": 0},
                {
                    "stdout": "worker_processes auto;\nworker_connections 1024;\n",
                    "stderr": "",
                    "returncode": 0,
                },
            ]
        )

        result = await nginx_config(plugin, {})
        assert result.status == Status.HEALTHY
        assert result.data["config_test_ok"] is True

    @pytest.mark.asyncio
    async def test_nginx_config_invalid(self):
        """Конфигурация невалидна (returncode!=0)"""
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_config
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NginxPlugin)
        plugin._run_command = AsyncMock(
            side_effect=[
                {"stdout": "", "stderr": "nginx: [emerg] unexpected end of file", "returncode": 1},
                {"stdout": "", "stderr": "", "returncode": 0},
                {"stdout": "", "stderr": "", "returncode": 0},
                {"stdout": "", "stderr": "", "returncode": 0},
                {"stdout": "Not found", "stderr": "", "returncode": 0},
            ]
        )

        result = await nginx_config(plugin, {})
        assert result.status == Status.HEALTHY
        assert result.data["config_test_ok"] is False


class TestLinuxFirewall:
    @pytest.mark.asyncio
    async def test_firewall_clean(self):
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_firewall
        from mcp_linx.types import Status

        plugin = _make_plugin(LinuxPlugin, {})
        plugin._run_command = AsyncMock(
            side_effect=[
                {"stdout": "", "stderr": "", "returncode": 0},
                {
                    "stdout": "0: from all lookup local\n32766: from all lookup main\n",
                    "stderr": "",
                    "returncode": 0,
                },
                {
                    "stdout": "broadcast 127.0.0.0 dev lo table local\n",
                    "stderr": "",
                    "returncode": 0,
                },
                {"stdout": "default via 10.0.0.1 dev eth0\n", "stderr": "", "returncode": 0},
                {"stdout": "", "stderr": "", "returncode": 0},
                {"stdout": "Status: inactive\n", "stderr": "", "returncode": 0},
            ]
        )
        result = await linux_firewall(plugin, {})
        assert result.status == Status.HEALTHY
        assert result.data["marks"] == []

    @pytest.mark.asyncio
    async def test_firewall_blackhole_detected(self):
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_firewall
        from mcp_linx.types import Status

        plugin = _make_plugin(LinuxPlugin, {})
        plugin._run_command = AsyncMock(
            side_effect=[
                {
                    "stdout": "table inet netpolicy {\n chain output {\n meta skuid www-data tcp dport 8080 meta mark set 0x64\n }\n}\n",
                    "stderr": "",
                    "returncode": 0,
                },
                {"stdout": "100: from all fwmark 0x64 lookup 100\n", "stderr": "", "returncode": 0},
                {"stdout": "blackhole default\n", "stderr": "", "returncode": 0},
                {
                    "stdout": "broadcast 127.0.0.0 dev lo table local\n",
                    "stderr": "",
                    "returncode": 0,
                },
                {"stdout": "default via 10.0.0.1 dev eth0\n", "stderr": "", "returncode": 0},
                {"stdout": "", "stderr": "", "returncode": 0},
                {"stdout": "Status: inactive\n", "stderr": "", "returncode": 0},
            ]
        )
        result = await linux_firewall(plugin, {})
        assert result.status == Status.DEGRADED
        assert result.data["marks"][0]["mark"] == "0x64"
        assert any("blackhole" in s for s in result.suggestions)
