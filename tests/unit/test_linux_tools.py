"""Unit tests for Linux diagnostic tools."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from conftest import make_plugin as _make_plugin


class TestLinuxDiagnosticTools:
    @pytest.mark.asyncio
    async def test_linux_logs_journal_quotes_filters_and_analyzes(self):
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_logs
        from mcp_linx.types import Status

        plugin = _make_plugin(
            LinuxPlugin,
            {
                "_run_command": {
                    "stdout": "boot ok\nWARNING disk\nERROR failed\n",
                    "stderr": "",
                    "returncode": 0,
                }
            },
        )

        result = await linux_logs(
            plugin,
            {
                "log_type": "journal",
                "since": "30 min ago; reboot",
                "priority": "warning",
                "lines": 600,
                "host": "web-1",
            },
        )

        assert result.status == Status.HEALTHY
        assert result.data["analysis"] == {
            "error_count": 1,
            "warning_count": 1,
            "info_count": 2,
        }
        plugin._run_command.assert_awaited_once_with(
            "journalctl --since='30 min ago; reboot' -p warning -n 500", host="web-1"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("log_type", "expected_command"),
        [
            ("auth", "tail -n 20 /var/log/auth.log"),
            ("kern", "tail -n 20 /var/log/kern.log"),
            ("messages", "tail -n 20 /var/log/syslog"),
            ("cron.log", "tail -n 20 /var/log/cron.log"),
        ],
    )
    async def test_linux_logs_supports_each_allowlisted_source(self, log_type, expected_command):
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_logs

        plugin = _make_plugin(
            LinuxPlugin,
            {"_run_command": {"stdout": "ok", "stderr": "", "returncode": 0}},
        )

        result = await linux_logs(plugin, {"log_type": log_type, "lines": 20})

        assert result.status.value == "healthy"
        plugin._run_command.assert_awaited_once_with(expected_command, host=None)

    @pytest.mark.asyncio
    async def test_linux_logs_returns_command_failure(self):
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_logs
        from mcp_linx.types import Status

        plugin = _make_plugin(
            LinuxPlugin,
            {"_run_command": {"stdout": "", "stderr": "permission denied", "returncode": 1}},
        )

        result = await linux_logs(plugin, {"log_type": "auth"})

        assert result.status == Status.ERROR
        assert result.error_message == "Failed to read logs: permission denied"

    @pytest.mark.asyncio
    async def test_linux_network_collects_all_sections_and_fallbacks(self):
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_network
        from mcp_linx.types import Status

        plugin = MagicMock(spec=LinuxPlugin)
        plugin._run_command = AsyncMock(
            side_effect=[
                {"stdout": "lo UNKNOWN 127.0.0.1/8"},
                {"stdout": "tcp LISTEN :80"},
                {},
                {"stdout": "default via 10.0.0.1"},
                {},
            ]
        )

        result = await linux_network(plugin, {"host": "edge"})

        assert result.status == Status.HEALTHY
        assert result.data == {
            "interfaces": "lo UNKNOWN 127.0.0.1/8",
            "listening_ports": "tcp LISTEN :80",
            "connections": "",
            "routes": "default via 10.0.0.1",
            "dns": "",
        }
        assert all(call.kwargs["host"] == "edge" for call in plugin._run_command.await_args_list)

    @pytest.mark.asyncio
    async def test_linux_firewall_rejects_invalid_probe_after_snapshot(self):
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_firewall
        from mcp_linx.types import Status

        plugin = _make_plugin(LinuxPlugin, {})
        plugin._run_command = AsyncMock(
            side_effect=[
                {"stdout": "NO_NFT"},
                {"stdout": "0: lookup local\n32766: lookup main"},
                {"stdout": ""},
                {"stdout": ""},
                {"stdout": ""},
                {"stdout": ""},
            ]
        )

        result = await linux_firewall(plugin, {"probe_dst": "10.0.0.1; reboot"})

        assert result.status == Status.ERROR
        assert "Invalid probe_dst" in result.error_message
        assert all(
            "ip route get" not in call.args[0] for call in plugin._run_command.await_args_list
        )

    @pytest.mark.asyncio
    async def test_linux_firewall_parses_detailed_marks_without_probe(self):
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_firewall

        plugin = _make_plugin(LinuxPlugin, {})
        plugin._run_command = AsyncMock(
            side_effect=[
                {
                    "stdout": (
                        'meta skuid "1000" tcp dport 443 meta mark set 0x2a\nmeta mark set 42\n'
                    )
                },
                {"stdout": ""},
                {"stdout": "default via 10.0.0.1"},
                {"stdout": "local dev lo"},
                {"stdout": "NO_IPTABLES"},
                {"stdout": "Status: inactive"},
            ]
        )

        result = await linux_firewall(plugin, {})

        assert result.status.value == "degraded"
        assert any("fwmark" in issue for issue in result.suggestions)
        assert result.data["marks"] == [
            {
                "skuid": "1000",
                "dport": 443,
                "mark": "0x2a",
                "rule": 'meta skuid "1000" tcp dport 443 meta mark set 0x2a',
            },
            {"mark": "42", "rule": "meta mark set 42"},
        ]
        assert "route_get" not in result.data

    @pytest.mark.asyncio
    async def test_linux_firewall_route_probe_and_simple_mark_are_degraded(self):
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_firewall
        from mcp_linx.types import Status

        plugin = _make_plugin(LinuxPlugin, {})
        plugin._run_command = AsyncMock(
            side_effect=[
                {"stdout": "meta mark set 42\n"},
                {"stdout": "100: fwmark 0x2a lookup 100\n"},
                {"stdout": "blackhole default\n"},
                {"stdout": "Error: table local unavailable"},
                {"stdout": "local table unavailable"},
                {"stdout": "NO_IPTABLES"},
                {"stdout": "NO_UFW"},
                {"stdout": "10.0.0.2 via 10.0.0.1 dev eth0\n"},
            ]
        )

        result = await linux_firewall(plugin, {"probe_dst": "10.0.0.2"})

        assert result.status == Status.DEGRADED
        assert result.data["marks"] == [{"mark": "42", "rule": "meta mark set 42"}]
        assert result.data["route_get"] == {"10.0.0.2": "10.0.0.2 via 10.0.0.1 dev eth0"}
        assert any("blackhole" in issue for issue in result.suggestions)

    @pytest.mark.asyncio
    async def test_linux_host_stats_reports_nonzero_and_empty_outputs(self, monkeypatch):
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_host_stats

        monkeypatch.setattr(sys, "platform", "linux")
        plugin = MagicMock(spec=LinuxPlugin)
        plugin._run_command = AsyncMock(
            side_effect=[
                {"stdout": "Linux", "stderr": "", "returncode": 0},
                {"stdout": "", "stderr": "", "returncode": 0},
                {"stdout": "", "stderr": "permission denied", "returncode": 1},
                {"stdout": "load", "stderr": "", "returncode": 0},
                {"stdout": "4", "stderr": "", "returncode": 0},
                {"stdout": "model", "stderr": "", "returncode": 0},
            ]
        )

        result = await linux_host_stats(plugin, {})

        assert result.status.value == "healthy"
        assert result.data["kernel"] == "Linux"
        assert result.data["uptime"] == "Error: empty output"
        assert result.data["memory"] == "Error: permission denied"

    @pytest.mark.asyncio
    async def test_linux_disk_and_memory_include_only_successful_commands(self):
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_disk, linux_memory
        from mcp_linx.types import Status

        plugin = _make_plugin(LinuxPlugin, {})
        plugin._run_command = AsyncMock(
            side_effect=[
                {"stdout": "disk", "stderr": "", "returncode": 0},
                {"stdout": "", "stderr": "inodes unavailable", "returncode": 1},
                {"stdout": "sda", "stderr": "", "returncode": 0},
                {"stdout": "swap", "stderr": "", "returncode": 0},
                {"stdout": "vm", "stderr": "", "returncode": 0},
            ]
        )

        disk = await linux_disk(plugin, {})
        assert disk.status == Status.HEALTHY
        assert disk.data == {
            "disk_usage": "disk",
            "block_devices": "sda",
            "swap": "swap",
            "vm_stats": "vm",
        }

        plugin._run_command = AsyncMock(
            side_effect=[
                {"stdout": "memory", "stderr": "", "returncode": 0},
                {"stdout": "vm", "stderr": "", "returncode": 0},
                {"stdout": "", "stderr": "not supported", "returncode": 1},
            ]
        )
        memory = await linux_memory(plugin, {"host": "db"})
        assert memory.status == Status.HEALTHY
        assert memory.data == {"memory": "memory", "vm_stats": "vm"}
        assert all(call.kwargs["host"] == "db" for call in plugin._run_command.await_args_list)

    @pytest.mark.asyncio
    async def test_linux_host_stats_handles_exceptions_and_macos_commands(self, monkeypatch):
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_host_stats
        from mcp_linx.types import Status

        monkeypatch.setattr(sys, "platform", "darwin")
        plugin = MagicMock(spec=LinuxPlugin)
        plugin._run_command = AsyncMock(side_effect=RuntimeError("adapter offline"))

        result = await linux_host_stats(plugin, {})

        assert result.status == Status.HEALTHY
        assert set(result.data) == {
            "kernel",
            "uptime",
            "memory",
            "load_avg",
            "cpu_count",
            "cpu_model",
            "platform",
        }
        assert "adapter offline" in result.data["kernel"]
        commands = [call.args[0] for call in plugin._run_command.await_args_list]
        assert commands[:5] == [
            "uname -a",
            "uptime",
            "vm_stat | head -20",
            "sysctl -n vm.loadavg",
            "sysctl -n hw.ncpu",
        ]
        assert "machdep.cpu.brand_string" in commands[5]

    @pytest.mark.parametrize(
        ("log_type", "expected_path"),
        [
            ("auth", "/var/log/auth.log"),
            ("kern", "/var/log/kern.log"),
            ("syslog", "/var/log/syslog"),
            ("messages", "/var/log/syslog"),
            ("dmesg", "/var/log/dmesg"),
        ],
    )
    @pytest.mark.asyncio
    async def test_linux_logs_supports_allowlisted_file_variants(self, log_type, expected_path):
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_logs
        from mcp_linx.types import Status

        plugin = _make_plugin(
            LinuxPlugin,
            {"_run_command": {"stdout": "ok", "stderr": "", "returncode": 0}},
        )

        result = await linux_logs(plugin, {"log_type": log_type, "lines": 25, "host": "node"})

        assert result.status == Status.HEALTHY
        plugin._run_command.assert_awaited_once_with(f"tail -n 25 {expected_path}", host="node")

    @pytest.mark.asyncio
    async def test_linux_logs_rejects_unknown_type_without_command(self):
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_logs
        from mcp_linx.types import Status

        plugin = _make_plugin(LinuxPlugin, {})

        result = await linux_logs(plugin, {"log_type": "../../etc/shadow"})

        assert result.status == Status.ERROR
        assert "Invalid log_type" in result.error_message
        plugin._run_command.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_linux_disk_and_memory_omit_failed_sections(self):
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_disk, linux_memory
        from mcp_linx.types import Status

        plugin = _make_plugin(
            LinuxPlugin,
            {"_run_command": {"stdout": "", "stderr": "not available", "returncode": 1}},
        )

        disk = await linux_disk(plugin, {"host": "node"})
        memory = await linux_memory(plugin, {"host": "node"})

        assert disk.status == Status.HEALTHY
        assert disk.data == {}
        assert memory.status == Status.HEALTHY
        assert memory.data == {}
        assert plugin._run_command.await_count == 8

    @pytest.mark.asyncio
    async def test_linux_host_stats_reports_failed_and_empty_commands(self):
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_host_stats

        plugin = _make_plugin(LinuxPlugin, {})
        plugin._run_command = AsyncMock(
            side_effect=[
                {"stdout": "", "stderr": "", "returncode": 0},
                {"stdout": "", "stderr": "permission denied", "returncode": 1},
            ]
        )

        result = await linux_host_stats(plugin, {})

        assert result.data["kernel"] == "Error: empty output"
        assert result.data["uptime"] == "Error: permission denied"

    @pytest.mark.asyncio
    async def test_linux_processes_filter_parse_empty_malformed_and_failure(self):
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_processes
        from mcp_linx.types import Status

        plugin = MagicMock(spec=LinuxPlugin)
        plugin._run_command = AsyncMock(
            return_value={
                "stdout": (
                    "USER PID CPU MEM VSZ RSS TTY STAT START TIME COMMAND\n"
                    "root 10 1.0 2.0 100 200 ? S 10:00 0:01 /usr/bin/nginx -g daemon off;\n"
                    "malformed row\n"
                    "  \n"
                ),
                "stderr": "",
                "returncode": 0,
            }
        )

        result = await linux_processes(
            plugin, {"filter": "nginx worker", "limit": 1000, "host": "web"}
        )

        assert result.status == Status.HEALTHY
        assert result.data["count"] == 1
        assert result.data["processes"][0]["pid"] == "10"
        assert result.data["processes"][0]["command"] == "/usr/bin/nginx -g daemon off;"
        assert plugin._run_command.await_args.args[0] == (
            "ps aux | grep -i 'nginx worker' | head -100"
        )

        plugin._run_command.return_value = {"stdout": "header", "stderr": "", "returncode": 0}
        empty = await linux_processes(plugin, {})
        assert empty.data == {"processes": [], "count": 0}
        assert plugin._run_command.await_args.args[0] == "ps aux | head -51"

        plugin._run_command.return_value = {
            "stdout": "",
            "stderr": "ps failed",
            "returncode": 1,
        }
        failed = await linux_processes(plugin, {})
        assert failed.status == Status.ERROR
        assert failed.error_message == "Failed to get processes: ps failed"

    @pytest.mark.asyncio
    async def test_linux_execute_command_requires_command_and_forwards_timeout(self):
        from mcp_linx.plugins.linux import LinuxPlugin
        from mcp_linx.plugins.linux.tools import linux_execute_command
        from mcp_linx.types import Status

        plugin = _make_plugin(
            LinuxPlugin,
            {"_run_command": {"stdout": "uptime", "stderr": "", "returncode": 0}},
        )

        missing = await linux_execute_command(plugin, {})
        assert missing.status == Status.ERROR
        assert missing.error_message == "Command is required"
        plugin._run_command.assert_not_awaited()

        result = await linux_execute_command(
            plugin, {"command": "uptime", "timeout": 7, "host": "edge"}
        )
        assert result.status == Status.HEALTHY
        assert result.data["stdout"] == "uptime"
        plugin._run_command.assert_awaited_once_with("uptime", 7, host="edge")
