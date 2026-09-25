"""Unit tests for linux_file_diagnostics."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_linx.plugins.linux import LinuxPlugin
from mcp_linx.security import SecurityError
from mcp_linx.types import Status


def _result(stdout: str = "", *, returncode: int = 0, stderr: str = "") -> dict[str, object]:
    return {"stdout": stdout, "stderr": stderr, "returncode": returncode}


def _healthy_results(*, attributes: str = "--------------e-------") -> list[dict[str, object]]:
    return [
        _result("644|-rw-r--r--|service|service|1003|1003|42|regular file"),
        _result("f: /var/log/service.log\n"),
        _result(f"{attributes} /var/log/service.log\n"),
        _result("TARGET / SOURCE / FSTYPE ext4 OPTIONS rw\n"),
        _result("Filesystem Size Used Avail Use% Mounted on\n/dev/vda1 9G 1G 8G 12% /\n"),
        _result("User=service\nGroup=service\nMainPID=42\n"),
    ]


def _plugin(*, config: dict[str, object] | None = None) -> MagicMock:
    plugin = MagicMock(spec=LinuxPlugin)
    plugin._config = config or {}
    plugin._run_command = AsyncMock()
    plugin._run_privileged = AsyncMock(return_value=_result())
    return plugin


class TestLinuxFileDiagnostics:
    @pytest.mark.asyncio
    async def test_collects_file_system_unit_and_privileged_write_status(self):
        from mcp_linx.plugins.linux.tools import linux_file_diagnostics

        plugin = _plugin(config={"privileged_tools": True})
        plugin._run_command.side_effect = _healthy_results()

        result = await linux_file_diagnostics(
            plugin,
            {
                "path": "/var/log/service.log",
                "unit": "service.service",
                "host": "edge",
                "timeout": 12,
            },
        )

        assert result.status == Status.HEALTHY
        assert result.data["file_exists"] is True
        assert result.data["stat"]["owner"] == "service"
        assert result.data["attributes"]["immutable"] is False
        assert result.data["systemd"]["properties"]["MainPID"] == "42"
        assert result.data["write_check"] == {
            "user": "service",
            "status": "ok",
            "writable": True,
            "returncode": 0,
            "error": "",
        }
        plugin._run_privileged.assert_awaited_once_with(
            "runuser -u service -- test -w /var/log/service.log", 12, host="edge"
        )
        assert plugin._run_command.await_count == 6
        assert plugin._run_command.await_args_list[0].args[0].startswith("stat ")

    @pytest.mark.asyncio
    async def test_reports_immutable_and_skips_privileged_write_check_by_default(self):
        from mcp_linx.plugins.linux.tools import linux_file_diagnostics

        results = _healthy_results(attributes="----i---------e-------")
        plugin = _plugin()
        plugin._run_command.side_effect = results

        result = await linux_file_diagnostics(
            plugin, {"path": "/var/log/service.log", "unit": "service.service"}
        )

        assert result.status == Status.DEGRADED
        assert result.data["attributes"]["immutable"] is True
        assert result.data["write_check"]["status"] == "skipped"
        assert "immutable attribute" in " ".join(result.suggestions)
        plugin._run_privileged.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failed_write_check_is_degraded(self):
        from mcp_linx.plugins.linux.tools import linux_file_diagnostics

        plugin = _plugin(config={"privileged_tools": True})
        plugin._run_command.side_effect = _healthy_results()
        plugin._run_privileged.return_value = _result(
            "runuser: permission denied", returncode=1, stderr="permission denied"
        )

        result = await linux_file_diagnostics(
            plugin, {"path": "/var/log/service.log", "user": "service"}
        )

        assert result.status == Status.DEGRADED
        assert result.data["write_check"]["writable"] is False
        assert "cannot write" in " ".join(result.suggestions)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "params",
        [
            {"path": "relative.log"},
            {"path": "/tmp/file", "unit": "../evil"},
            {"path": "/tmp/file", "user": "bad user"},
            {"path": "/tmp/file", "timeout": "not-an-int"},
        ],
    )
    async def test_rejects_invalid_parameters_before_running_commands(self, params):
        from mcp_linx.plugins.linux.tools import linux_file_diagnostics

        plugin = _plugin()
        result = await linux_file_diagnostics(plugin, params)

        assert result.status == Status.ERROR
        plugin._run_command.assert_not_awaited()
        plugin._run_privileged.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_file_returns_degraded_diagnostics(self):
        from mcp_linx.plugins.linux.tools import linux_file_diagnostics

        plugin = _plugin()
        plugin._run_command.return_value = _result(
            "No such file or directory", returncode=1, stderr="No such file or directory"
        )

        result = await linux_file_diagnostics(plugin, {"path": "/var/log/missing.log"})

        assert result.status == Status.DEGRADED
        assert result.data["file_exists"] is False
        assert result.data["errors"]


class TestLinuxPrivilegedRunner:
    @pytest.mark.asyncio
    async def test_accepts_only_test_w_probe(self):
        class Adapter:
            def __init__(self):
                self.calls = []

            async def execute_command(self, command, timeout=None):
                self.calls.append((command, timeout))
                return _result()

            async def connect(self):
                pass

            async def disconnect(self):
                pass

        plugin = LinuxPlugin()
        await plugin.initialize({"security": {"command_timeout_seconds": 9}})
        adapter = Adapter()
        plugin._adapter = adapter  # type: ignore[assignment]

        result = await plugin._run_privileged("runuser -u service -- test -w /var/log/service.log")

        assert result["returncode"] == 0
        assert adapter.calls == [("runuser -u service -- test -w /var/log/service.log", 9)]
        with pytest.raises(SecurityError):
            await plugin._run_privileged("runuser -u service -- id")
        with pytest.raises(SecurityError):
            await plugin._run_privileged("runuser -u service -- test -w /tmp/a; id")
