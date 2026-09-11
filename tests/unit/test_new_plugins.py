"""Unit tests for new plugins: redis, systemd, netdiag"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_plugin(plugin_class, methods: dict):
    plugin = MagicMock(spec=plugin_class)
    for name, ret in methods.items():
        setattr(plugin, name, AsyncMock(return_value=ret))
    return plugin


class TestRedisTools:
    @pytest.mark.asyncio
    async def test_redis_ping_ok(self):
        from mcp_linx.plugins.redis import RedisPlugin
        from mcp_linx.plugins.redis.tools import redis_ping
        from mcp_linx.types import Status

        plugin = _make_plugin(RedisPlugin, {
            "_run_redis_cli": {"stdout": "PONG\n", "stderr": "", "returncode": 0},
        })
        result = await redis_ping(plugin, {})
        assert result.status == Status.HEALTHY
        assert result.data["reachable"] is True

    @pytest.mark.asyncio
    async def test_redis_ping_fail(self):
        from mcp_linx.plugins.redis import RedisPlugin
        from mcp_linx.plugins.redis.tools import redis_ping
        from mcp_linx.types import Status

        plugin = _make_plugin(RedisPlugin, {
            "_run_redis_cli": {"stdout": "", "stderr": "Connection refused", "returncode": 1},
        })
        result = await redis_ping(plugin, {})
        assert result.status == Status.UNHEALTHY

    @pytest.mark.asyncio
    async def test_redis_info_bad_section(self):
        from mcp_linx.plugins.redis import RedisPlugin
        from mcp_linx.plugins.redis.tools import redis_info
        from mcp_linx.types import Status

        plugin = _make_plugin(RedisPlugin, {})
        result = await redis_info(plugin, {"section": "nope"})
        assert result.status == Status.ERROR

    @pytest.mark.asyncio
    async def test_redis_memory_evictions(self):
        from mcp_linx.plugins.redis import RedisPlugin
        from mcp_linx.plugins.redis.tools import redis_memory
        from mcp_linx.types import Status

        plugin = _make_plugin(RedisPlugin, {
            "_run_redis_cli": {
                "stdout": "used_memory:100\nused_memory_human:100B\nused_memory_peak:120\n"
                          "mem_fragmentation_ratio:1.1\nmaxmemory:100\nmaxmemory_policy:allkeys-lru\n"
                          "evicted_keys:50\nexpired_keys:5\n",
                "stderr": "", "returncode": 0,
            },
        })
        result = await redis_memory(plugin, {})
        assert result.status == Status.DEGRADED
        assert any("evicted" in s for s in result.suggestions)


class TestSystemdTools:
    @pytest.mark.asyncio
    async def test_service_status_active(self):
        from mcp_linx.plugins.systemd import SystemdPlugin
        from mcp_linx.plugins.systemd.tools import service_status
        from mcp_linx.types import Status

        plugin = _make_plugin(SystemdPlugin, {})
        plugin._run = AsyncMock(side_effect=[
            {"stdout": "active\n", "stderr": "", "returncode": 0},
            {"stdout": "enabled\n", "stderr": "", "returncode": 0},
            {"stdout": "unit status\n", "stderr": "", "returncode": 0},
        ])
        result = await service_status(plugin, {"unit": "nginx.service"})
        assert result.status == Status.HEALTHY

    @pytest.mark.asyncio
    async def test_service_status_bad_unit(self):
        from mcp_linx.plugins.systemd import SystemdPlugin
        from mcp_linx.plugins.systemd.tools import service_status
        from mcp_linx.types import Status

        plugin = _make_plugin(SystemdPlugin, {})
        result = await service_status(plugin, {"unit": "../evil"})
        assert result.status == Status.ERROR

    @pytest.mark.asyncio
    async def test_failed_units_empty(self):
        from mcp_linx.plugins.systemd import SystemdPlugin
        from mcp_linx.plugins.systemd.tools import failed_units
        from mcp_linx.types import Status

        plugin = _make_plugin(SystemdPlugin, {
            "_run": {"stdout": "", "stderr": "", "returncode": 0},
        })
        result = await failed_units(plugin, {})
        assert result.status == Status.HEALTHY
        assert result.data["count"] == 0

    @pytest.mark.asyncio
    async def test_service_ip_filter_no_filter(self):
        from mcp_linx.plugins.systemd import SystemdPlugin
        from mcp_linx.plugins.systemd.tools import service_ip_filter
        from mcp_linx.types import Status

        plugin = _make_plugin(SystemdPlugin, {})
        plugin._run = AsyncMock(side_effect=[
            {"stdout": "IPAddressAllow=\nIPAddressDeny=\nIPAccounting=no\n", "stderr": "", "returncode": 0},
            {"stdout": "NO_CGROUP_BPF\n", "stderr": "", "returncode": 0},
            {"stdout": "", "stderr": "", "returncode": 0},
            {"stdout": "", "stderr": "", "returncode": 0},
        ])
        result = await service_ip_filter(plugin, {"unit": "nginx.service"})
        assert result.status == Status.HEALTHY
        assert result.data["verdict"] == "no_ip_filter_detected"

    @pytest.mark.asyncio
    async def test_service_ip_filter_hidden_filter(self):
        from mcp_linx.plugins.systemd import SystemdPlugin
        from mcp_linx.plugins.systemd.tools import service_ip_filter
        from mcp_linx.types import Status

        plugin = _make_plugin(SystemdPlugin, {})
        plugin._run = AsyncMock(side_effect=[
            {"stdout": "IPAddressAllow=\nIPAddressDeny=\nIPAccounting=no\n", "stderr": "", "returncode": 0},
            {"stdout": "ID 106 cgroup_skb name sd_fw_egress attached\n", "stderr": "", "returncode": 0},
            {"stdout": "106: cgroup_skb name sd_fw_egress tag abc\n", "stderr": "", "returncode": 0},
            {"stdout": "11: lpm_trie name 4_app flags 0x1\n", "stderr": "", "returncode": 0},
            {"stdout": "key: 08 00 00 00 7f 00 00 00 value: 01 00 00 00\n", "stderr": "", "returncode": 0},
        ])
        result = await service_ip_filter(plugin, {"unit": "app.service"})
        assert result.status == Status.DEGRADED
        assert result.data["verdict"] == "hidden_filter"
        assert result.data["effective_allow"] == ["127.0.0.0/8"]

    @pytest.mark.asyncio
    async def test_service_ip_filter_bad_unit(self):
        from mcp_linx.plugins.systemd import SystemdPlugin
        from mcp_linx.plugins.systemd.tools import service_ip_filter
        from mcp_linx.types import Status

        plugin = _make_plugin(SystemdPlugin, {})
        result = await service_ip_filter(plugin, {"unit": "../evil"})
        assert result.status == Status.ERROR


class TestNetdiagTools:
    @pytest.mark.asyncio
    async def test_http_check_bad_url(self):
        from mcp_linx.plugins.netdiag import NetdiagPlugin
        from mcp_linx.plugins.netdiag.tools import http_check
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NetdiagPlugin)
        result = await http_check(plugin, {"url": "notaurl"})
        assert result.status == Status.ERROR

    @pytest.mark.asyncio
    async def test_dns_resolve_empty(self):
        from mcp_linx.plugins.netdiag import NetdiagPlugin
        from mcp_linx.plugins.netdiag.tools import dns_resolve
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NetdiagPlugin)
        result = await dns_resolve(plugin, {"name": ""})
        assert result.status == Status.ERROR

    @pytest.mark.asyncio
    async def test_tcp_connect_empty_host(self):
        from mcp_linx.plugins.netdiag import NetdiagPlugin
        from mcp_linx.plugins.netdiag.tools import tcp_connect
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NetdiagPlugin)
        result = await tcp_connect(plugin, {"host": ""})
        assert result.status == Status.ERROR

    @pytest.mark.asyncio
    async def test_tcp_connect_as_disabled(self):
        from mcp_linx.plugins.netdiag import NetdiagPlugin
        from mcp_linx.plugins.netdiag.tools import tcp_connect_as
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NetdiagPlugin)
        plugin._config = {}
        result = await tcp_connect_as(plugin, {"host": "127.0.0.1", "port": 8080, "user": "www-data"})
        assert result.status == Status.ERROR
        assert "privileged_tools" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_tcp_connect_as_bad_user(self):
        from mcp_linx.plugins.netdiag import NetdiagPlugin
        from mcp_linx.plugins.netdiag.tools import tcp_connect_as
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NetdiagPlugin)
        plugin._config = {"privileged_tools": True}
        result = await tcp_connect_as(plugin, {"host": "127.0.0.1", "port": 8080, "user": "root"})
        assert result.status == Status.ERROR

    @pytest.mark.asyncio
    async def test_tcp_connect_as_ok(self):
        from mcp_linx.plugins.netdiag import NetdiagPlugin
        from mcp_linx.plugins.netdiag.tools import tcp_connect_as
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NetdiagPlugin)
        plugin._config = {"privileged_tools": True}
        plugin._run_privileged = AsyncMock(return_value={"stdout": "", "stderr": "", "returncode": 0})
        result = await tcp_connect_as(plugin, {"host": "127.0.0.1", "port": 8080, "user": "www-data"})
        assert result.status == Status.HEALTHY
        assert result.data["reachable"] is True

    @pytest.mark.asyncio
    async def test_tcpdump_probe_disabled(self):
        from mcp_linx.plugins.netdiag import NetdiagPlugin
        from mcp_linx.plugins.netdiag.tools import tcpdump_probe
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NetdiagPlugin)
        plugin._config = {}
        result = await tcpdump_probe(plugin, {"host": "127.0.0.1", "port": 8080})
        assert result.status == Status.ERROR
        assert "privileged_tools" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_tcpdump_probe_no_packets(self):
        from mcp_linx.plugins.netdiag import NetdiagPlugin
        from mcp_linx.plugins.netdiag.tools import tcpdump_probe
        from mcp_linx.types import Status

        plugin = MagicMock(spec=NetdiagPlugin)
        plugin._config = {"privileged_tools": True}
        plugin._run_privileged = AsyncMock(return_value={"stdout": "tcpdump: listening\n0 packets captured\n", "stderr": "", "returncode": 0})
        result = await tcpdump_probe(plugin, {"host": "10.0.0.1", "port": 5432})
        assert result.status == Status.DEGRADED
        assert result.data["packets_seen"] == 0
