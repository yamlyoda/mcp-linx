"""Unit tests for base plugin tools: linux, nginx, docker, postgres (parts 1-3 merged)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from conftest import make_plugin as _make_plugin


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

        async def fake_run(command, timeout=30, host=None):
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

        async def fake_run(command, timeout=30, host=None):
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


class TestNginxStubStatusParsing:
    @pytest.mark.asyncio
    async def test_stub_status_parses_metrics(self):
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_stub_status
        from mcp_linx.types import Status

        body = (
            "Active connections: 12\n"
            "server accepts handled requests\n"
            " 100 100 250\n"
            "Reading: 0 Writing: 2 Waiting: 10\n"
        )
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
        plugin.list_containers = AsyncMock(
            return_value=[
                {"id": "a1", "name": "old", "status": "exited", "image": "nginx"},
                {"id": "b2", "name": "web", "status": "running", "image": "app"},
            ]
        )
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


class TestDockerPruneReadonly:
    """Wave 9: `security.readonly` закрывает некомандный write-путь (Docker prune)."""

    def _plugin(self, readonly: bool):
        from mcp_linx.plugins.docker import DockerPlugin
        from mcp_linx.security import SecurityGuard

        plugin = DockerPlugin()
        plugin._security = SecurityGuard({"readonly": readonly})
        adapter = MagicMock()
        adapter.prune_containers = AsyncMock(return_value={"SpaceReclaimed": 1})
        adapter.list_containers = AsyncMock(return_value=[])
        plugin._adapter = adapter
        return plugin, adapter

    @pytest.mark.asyncio
    async def test_execute_blocked_in_readonly(self):
        from mcp_linx.plugins.docker.tools import docker_prune
        from mcp_linx.types import Status

        plugin, adapter = self._plugin(readonly=True)

        result = await docker_prune(plugin, {"execute": True, "confirm": True})

        assert result.status == Status.ERROR
        assert "readonly" in result.error_message
        adapter.prune_containers.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dry_run_allowed_in_readonly(self):
        from mcp_linx.plugins.docker.tools import docker_prune
        from mcp_linx.types import Status

        plugin, adapter = self._plugin(readonly=True)

        result = await docker_prune(plugin, {})

        assert result.status == Status.HEALTHY
        assert result.data["mode"] == "dry-run"
        adapter.prune_containers.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_execute_allowed_when_readonly_disabled(self):
        from mcp_linx.plugins.docker.tools import docker_prune
        from mcp_linx.types import Status

        plugin, adapter = self._plugin(readonly=False)

        result = await docker_prune(plugin, {"execute": True, "confirm": True})

        assert result.status == Status.HEALTHY
        adapter.prune_containers.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_plugin_method_raises_security_error_in_readonly(self):
        """Барьер стоит в методе плагина: обход tool-проверки не помогает."""
        from mcp_linx.security import SecurityError

        plugin, adapter = self._plugin(readonly=True)

        with pytest.raises(SecurityError, match="readonly"):
            await plugin.prune_containers()

        adapter.prune_containers.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_initialize_wires_guard_from_config(self, monkeypatch):
        import mcp_linx.plugins.docker as mod

        class _FakeAdapter:
            def __init__(self, config: Any) -> None: ...

            async def connect(self) -> None: ...

        monkeypatch.setattr(mod, "DockerAdapter", _FakeAdapter)
        plugin = mod.DockerPlugin()

        await plugin.initialize({"security": {"readonly": False}})

        assert plugin._security is not None
        assert plugin._security.readonly is False

    def test_guard_defaults_to_readonly(self):
        from mcp_linx.security import SecurityGuard

        assert SecurityGuard().readonly is True
        assert SecurityGuard({"readonly": False}).readonly is False


class TestPostgresTools:
    @pytest.mark.asyncio
    async def test_pg_connections_ok(self):
        from mcp_linx.plugins.postgres import PostgresPlugin
        from mcp_linx.plugins.postgres.tools import pg_connections
        from mcp_linx.types import Status

        plugin = _make_plugin(
            PostgresPlugin,
            {
                "_execute_query": [{"state": "active"}, {"state": "idle"}],
            },
        )
        result = await pg_connections(plugin, {})
        assert result.status == Status.HEALTHY

    @pytest.mark.asyncio
    async def test_pg_connections_error(self):
        from mcp_linx.plugins.postgres import PostgresPlugin
        from mcp_linx.plugins.postgres.tools import pg_connections
        from mcp_linx.types import Status

        plugin = MagicMock(spec=PostgresPlugin)
        plugin._execute_query = AsyncMock(side_effect=Exception("no pg"))
        result = await pg_connections(plugin, {})
        assert result.status == Status.ERROR

    @pytest.mark.asyncio
    async def test_pg_tables_bad_schema(self):
        from mcp_linx.plugins.postgres import PostgresPlugin
        from mcp_linx.plugins.postgres.tools import pg_tables
        from mcp_linx.types import Status

        plugin = MagicMock(spec=PostgresPlugin)
        plugin._execute_query = AsyncMock()
        result = await pg_tables(plugin, {"schema": "evil; DROP TABLE x"})
        assert result.status == Status.ERROR
        plugin._execute_query.assert_not_awaited()
