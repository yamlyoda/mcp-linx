"""Unit tests for Nginx diagnostic tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from conftest import make_plugin as _make_plugin


def _http_client(*responses: object) -> tuple[MagicMock, MagicMock]:
    client = MagicMock()
    client.get = AsyncMock(side_effect=list(responses))
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    return context, client


class TestNginxDiagnosticTools:
    @pytest.mark.asyncio
    async def test_nginx_config_collects_health_snapshot(self):
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_config
        from mcp_linx.types import Status

        plugin = _make_plugin(NginxPlugin, {})
        plugin._run_command = AsyncMock(
            side_effect=[
                {"stdout": "syntax ok", "stderr": "", "returncode": 0},
                {"stdout": "user nginx;", "stderr": "", "returncode": 0},
                {"stdout": "default", "stderr": "", "returncode": 0},
                {"stdout": "ssl_certificate /cert.pem", "stderr": "", "returncode": 0},
                {"stdout": "worker_processes auto", "stderr": "", "returncode": 0},
            ]
        )

        result = await nginx_config(plugin, {"host": "edge"})

        assert result.status == Status.HEALTHY
        assert result.data["config_test_ok"] is True
        assert result.data["main_config"] == "user nginx;"
        assert result.data["ssl"] == "ssl_certificate /cert.pem"
        assert all(call.kwargs["host"] == "edge" for call in plugin._run_command.await_args_list)

    @pytest.mark.asyncio
    async def test_nginx_config_uses_stderr_fallbacks(self):
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_config
        from mcp_linx.types import Status

        plugin = _make_plugin(NginxPlugin, {})
        plugin._run_command = AsyncMock(
            side_effect=[
                {"stderr": "nginx: [emerg] invalid", "returncode": 1},
                {},
                {},
                {},
                {},
            ]
        )

        result = await nginx_config(plugin, {})

        assert result.status == Status.HEALTHY
        assert result.data == {
            "config_test_output": "nginx: [emerg] invalid",
            "config_test_ok": False,
            "main_config": "Not found",
            "sites": "Not found",
            "ssl": "Not found",
            "worker_settings": "Not found",
        }

    @pytest.mark.asyncio
    async def test_nginx_upstream_parses_timeouts_and_marks_timeout_match(self):
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_upstream
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NginxPlugin)
        plugin._run_command = AsyncMock(
            side_effect=[
                {
                    "stdout": (
                        "proxy_connect_timeout 500ms;\n"
                        "proxy_read_timeout 2m;\n"
                        "proxy_connect_timeout 3s;\n"
                        "proxy_connect_timeout;\n"
                    )
                },
                {
                    "stdout": (
                        "upstream backend {\n"
                        "server 127.0.0.1:8080;\n"
                        "server https://api.internal/check;\n"
                        "server 127.0.0.1:8080;\n"
                        "server ;\n"
                        "server\n"
                    )
                },
            ]
        )
        client_context, client = _http_client(
            httpx.Response(504, request=httpx.Request("GET", "http://127.0.0.1:8080")),
            RuntimeError("ConnectTimeout: connect timed out"),
        )

        with patch("httpx.AsyncClient", return_value=client_context):
            result = await nginx_upstream(
                plugin, {"timeout": 90, "max_servers": 50, "host": "edge"}
            )

        assert result.status == Status.DEGRADED
        assert result.data["proxy_connect_timeout_s"] == 3.0
        assert result.data["proxy_read_timeout_s"] == 120.0
        assert result.data["upstream_servers"] == [
            "127.0.0.1:8080",
            "https://api.internal/check",
        ]
        assert result.data["checks"][0]["status_code"] == 504
        assert result.data["checks"][1]["matches_proxy_connect_timeout"] is True
        assert client.get.await_args_list[0].args[0] == "http://127.0.0.1:8080"
        assert client.get.await_args_list[1].args[0] == "https://api.internal/check"

    @pytest.mark.asyncio
    async def test_nginx_upstream_ignores_timeout_probe_exception(self):
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_upstream
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NginxPlugin)
        plugin._run_command = AsyncMock(
            side_effect=[RuntimeError("config unavailable"), {"stdout": "server 127.0.0.1:8080;"}]
        )
        client_context, _ = _http_client(httpx.Response(200))

        with patch("httpx.AsyncClient", return_value=client_context):
            result = await nginx_upstream(plugin, {})

        assert result.status == Status.HEALTHY
        assert "proxy_connect_timeout_s" not in result.data
        assert result.data["live_servers"] == ["127.0.0.1:8080"]

    @pytest.mark.asyncio
    async def test_nginx_stub_status_requires_configured_url(self):
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_stub_status
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NginxPlugin)
        plugin._config = {}

        result = await nginx_stub_status(plugin, {})

        assert result.status == Status.ERROR
        assert "stub_status_url is not configured" in result.error_message

    @pytest.mark.asyncio
    async def test_nginx_upstream_skips_unix_socket(self):
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_upstream
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NginxPlugin)
        plugin._run_command = AsyncMock(
            side_effect=[{}, {"stdout": "server unix:/run/backend.sock;"}]
        )
        context, client = _http_client()

        with patch("httpx.AsyncClient", return_value=context):
            result = await nginx_upstream(plugin, {})

        assert result.status == Status.HEALTHY
        assert result.data["checks"] == [
            {
                "server": "unix:/run/backend.sock",
                "type": "socket",
                "status": "skipped",
                "note": "unix-socket: HTTP health check not applicable",
            }
        ]
        client.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_nginx_stub_status_reports_request_and_http_failures(self):
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_stub_status
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NginxPlugin)
        plugin._config = {"stub_status_url": "http://127.0.0.1/nginx_status"}

        failing_context, _ = _http_client(RuntimeError("connection refused"))
        with patch("httpx.AsyncClient", return_value=failing_context):
            failed = await nginx_stub_status(plugin, {"timeout": 1})
        assert failed.status == Status.ERROR
        assert "connection refused" in failed.error_message

        unavailable_context, _ = _http_client(
            httpx.Response(503, request=httpx.Request("GET", "http://127.0.0.1/nginx_status"))
        )
        with patch("httpx.AsyncClient", return_value=unavailable_context):
            unavailable = await nginx_stub_status(plugin, {})
        assert unavailable.status == Status.ERROR
        assert unavailable.error_message == "stub_status returned HTTP 503"

    @pytest.mark.asyncio
    async def test_nginx_stub_status_high_load_and_malformed_values_are_degraded(self):
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_stub_status
        from mcp_linx.types import Status

        body = (
            "Active connections: 5001\n"
            "Reading: 101 Writing: 2 Waiting: 3\n"
            "not-a-counter line\n"
            "7 8 9\n"
            "1 2 3 4\n"
        )
        plugin = MagicMock(spec=NginxPlugin)
        plugin._config = {"stub_status_url": "http://127.0.0.1/nginx_status"}
        context, _ = _http_client(
            httpx.Response(
                200,
                text=body,
                request=httpx.Request("GET", "http://127.0.0.1/nginx_status"),
            )
        )

        with patch("httpx.AsyncClient", return_value=context):
            result = await nginx_stub_status(plugin, {})

        assert result.status == Status.DEGRADED
        assert result.data["active_connections"] == 5001
        assert result.data["reading"] == 101
        assert result.data["accepted"] == 7
        assert result.data["handled"] == 8
        assert result.data["requests"] == 9
        assert any("High connection count" in issue for issue in result.suggestions)
        assert any("High reading count" in issue for issue in result.suggestions)

    @pytest.mark.asyncio
    async def test_nginx_status_collects_service_and_worker_data(self):
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_status
        from mcp_linx.types import Status

        plugin = _make_plugin(NginxPlugin, {})
        plugin._run_command = AsyncMock(
            side_effect=[
                {"stdout": "active", "returncode": 0},
                {"stdout": "syntax ok", "stderr": "", "returncode": 0},
                {"stdout": "", "stderr": "nginx version: nginx/1.28.0", "returncode": 0},
                {"stdout": "root 10 master nginx\nroot 11 worker nginx\n", "returncode": 0},
                {"stdout": "worker_processes auto", "stderr": "", "returncode": 0},
            ]
        )

        result = await nginx_status(plugin, {"host": "edge"})

        assert result.status == Status.HEALTHY
        assert result.data["systemctl_status"] == "active"
        assert result.data["systemctl_code"] == 0
        assert result.data["config_test_ok"] is True
        assert result.data["version"] == "nginx version: nginx/1.28.0"
        assert result.data["process_count"] == 2
        assert result.data["worker_config"] == "worker_processes auto"
        assert all(call.kwargs["host"] == "edge" for call in plugin._run_command.await_args_list)

    @pytest.mark.asyncio
    async def test_nginx_logs_analyzes_error_and_access_variants(self):
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_logs
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NginxPlugin)
        plugin._config = {
            "log_path": "/var/log/nginx",
            "access_log": "access.log",
            "error_log": "error.log",
        }
        plugin._run_command = AsyncMock(
            side_effect=[
                {
                    "stdout": "ERROR upstream timeout\nconnection refused\nnormal\n",
                    "stderr": "",
                    "returncode": 0,
                },
                {
                    "stdout": '"GET / 200 1\n"GET /old 301 1\n"GET /x 404 1\n"GET /x 503 1\n',
                    "stderr": "",
                    "returncode": 0,
                },
            ]
        )

        error_result = await nginx_logs(plugin, {"log_type": "error_full", "host": "edge"})
        assert error_result.status == Status.HEALTHY
        assert error_result.data["analysis"] == {
            "error_count": 1,
            "timeout_count": 1,
            "connection_refused_count": 1,
            "upstream_errors": 2,
        }
        assert plugin._run_command.await_args_list[0].args[0] == (
            "tail -n 100 /var/log/nginx/error.log"
        )

        access_result = await nginx_logs(plugin, {"log_type": "access_full", "lines": 600})
        assert access_result.status == Status.HEALTHY
        assert access_result.data["analysis"] == {
            "status_2xx": 1,
            "status_3xx": 1,
            "status_4xx": 1,
            "status_5xx": 1,
        }
        assert plugin._run_command.await_args_list[1].args[0] == (
            "tail -n 500 /var/log/nginx/access.log"
        )

    @pytest.mark.asyncio
    async def test_nginx_stub_status_tolerates_malformed_active_connections(self):
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_stub_status
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NginxPlugin)
        plugin._config = {"stub_status_url": "http://127.0.0.1/nginx_status"}
        body = "Active connections: invalid\nReading: 0 Writing: 1 Waiting: 4\n1 2 3\n"
        context, _ = _http_client(
            httpx.Response(
                200,
                text=body,
                request=httpx.Request("GET", "http://127.0.0.1/nginx_status"),
            )
        )

        with patch("httpx.AsyncClient", return_value=context):
            result = await nginx_stub_status(plugin, {"timeout": 99})

        assert result.status == Status.HEALTHY
        assert "active_connections" not in result.data
        assert result.data["requests"] == 3

    @pytest.mark.asyncio
    async def test_nginx_logs_rejects_bad_type_filename_and_command_failure(self):
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_logs
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NginxPlugin)
        plugin._config = {
            "log_path": "/var/log/nginx",
            "error_log": "error.log",
            "access_log": "access.log",
        }
        plugin._run_command = AsyncMock()

        invalid_path = await nginx_logs(plugin, {})
        plugin._config["log_path"] = "/tmp"
        bad_path = await nginx_logs(plugin, {})
        assert invalid_path.status == Status.ERROR
        assert bad_path.status == Status.ERROR
        assert "Invalid log_path" in bad_path.error_message
        plugin._run_command.reset_mock()

        plugin._config["log_path"] = "/var/log/nginx"
        plugin._config["access_log"] = "nested/access.log"
        invalid_access = await nginx_logs(plugin, {"log_type": "access"})
        assert invalid_access.status == Status.ERROR
        assert "Invalid access_log" in invalid_access.error_message

        plugin._config["log_path"] = "/var/log/nginx"
        plugin._config["access_log"] = "access.log"
        invalid_type = await nginx_logs(plugin, {"log_type": "syslog"})
        assert invalid_type.status == Status.ERROR
        assert "Invalid log_type" in invalid_type.error_message

        plugin._config["error_log"] = "../error.log"
        invalid_name = await nginx_logs(plugin, {"log_type": "error"})
        assert invalid_name.status == Status.ERROR
        assert "Invalid error_log" in invalid_name.error_message
        plugin._run_command.assert_not_awaited()

        plugin._config["error_log"] = "error.log"
        plugin._run_command.return_value = {
            "stdout": "",
            "stderr": "permission denied",
            "returncode": 1,
        }
        failed = await nginx_logs(plugin, {"log_type": "error"})
        assert failed.status == Status.ERROR
        assert failed.error_message == "Failed to read logs: permission denied"
