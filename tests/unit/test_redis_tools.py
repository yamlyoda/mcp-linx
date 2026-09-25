"""Unit tests для `plugins/redis/tools.py` (волна 14).

Без redis-server: `plugin._run_redis_cli` подменяется заготовленным выводом.
Покрываем парсинг INFO/CLIENT LIST/SLOWLOG, пороги degraded и ошибки redis-cli.
"""

from __future__ import annotations

import pytest
from conftest import make_plugin as _make_plugin

from mcp_linx.types import Status


def _redis(stdout: str, returncode: int = 0, stderr: str = ""):
    """RedisPlugin-двойник с ответом redis-cli."""
    from mcp_linx.plugins.redis import RedisPlugin

    return _make_plugin(
        RedisPlugin,
        {"_run_redis_cli": {"stdout": stdout, "stderr": stderr, "returncode": returncode}},
    )


class TestRedisInfo:
    @pytest.mark.asyncio
    async def test_parses_section(self):
        from mcp_linx.plugins.redis.tools import redis_info

        plugin = _redis("# Memory\r\nused_memory:1048576\r\nmaxmemory:2097152\r\n")
        result = await redis_info(plugin, {"section": "memory"})

        assert result.status == Status.HEALTHY
        assert result.data["section"] == "memory"
        assert result.data["info"]["used_memory"] == "1048576"
        assert result.data["info"]["maxmemory"] == "2097152"

    @pytest.mark.asyncio
    async def test_cli_failure(self):
        from mcp_linx.plugins.redis.tools import redis_info

        plugin = _redis("", returncode=1, stderr="Connection refused")
        result = await redis_info(plugin, {"section": "stats"})

        assert result.status == Status.ERROR
        assert "Connection refused" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_exception(self):
        from mcp_linx.plugins.redis.tools import redis_info

        plugin = _redis("")
        plugin._run_redis_cli.side_effect = RuntimeError("boom")
        result = await redis_info(plugin, {"section": "server"})

        assert result.status == Status.ERROR
        assert "boom" in (result.error_message or "")


class TestRedisClients:
    @pytest.mark.asyncio
    async def test_parses_client_list_and_counts_blocked(self):
        from mcp_linx.plugins.redis.tools import redis_clients

        stdout = (
            "id=1 addr=127.0.0.1:5001 name=app age=10 idle=0 cmd=get db=0\n"
            "id=2 addr=127.0.0.1:5002 name=worker age=20 idle=5 cmd=blpop db=0\n"
        )
        plugin = _redis(stdout)
        result = await redis_clients(plugin, {})

        assert result.status == Status.HEALTHY
        assert result.data["total"] == 2
        assert result.data["shown"] == 2
        assert result.data["blocked_clients"] == 1
        assert result.data["clients"][1]["cmd"] == "blpop"

    @pytest.mark.asyncio
    async def test_respects_limit(self):
        from mcp_linx.plugins.redis.tools import redis_clients

        stdout = "".join(
            f"id={i} addr=127.0.0.1:{5000 + i} name= age=1 idle=0 cmd=get db=0\n" for i in range(10)
        )
        plugin = _redis(stdout)
        result = await redis_clients(plugin, {"limit": 3})

        assert result.data["total"] == 10
        assert result.data["shown"] == 3

    @pytest.mark.asyncio
    async def test_cli_failure(self):
        from mcp_linx.plugins.redis.tools import redis_clients

        plugin = _redis("", returncode=1, stderr="NOAUTH")
        result = await redis_clients(plugin, {})

        assert result.status == Status.ERROR
        assert "NOAUTH" in (result.error_message or "")


class TestRedisSlowlog:
    @pytest.mark.asyncio
    async def test_empty_is_healthy(self):
        from mcp_linx.plugins.redis.tools import redis_slowlog

        plugin = _redis("")
        result = await redis_slowlog(plugin, {})

        assert result.status == Status.HEALTHY
        assert result.data["count"] == 0
        assert result.suggestions == []

    @pytest.mark.asyncio
    async def test_entries_are_degraded(self):
        from mcp_linx.plugins.redis.tools import redis_slowlog

        plugin = _redis("1) 1) (integer) 5\n    2) (integer) 1700000000\n")
        result = await redis_slowlog(plugin, {"count": 5})

        assert result.status == Status.DEGRADED
        assert result.data["count"] == 2
        assert any("медленные" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_cli_failure(self):
        from mcp_linx.plugins.redis.tools import redis_slowlog

        plugin = _redis("", returncode=1, stderr="ERR unknown command")
        result = await redis_slowlog(plugin, {})

        assert result.status == Status.ERROR


class TestRedisMemory:
    @pytest.mark.asyncio
    async def test_healthy(self):
        from mcp_linx.plugins.redis.tools import redis_memory

        plugin = _redis(
            "used_memory:1000000\nused_memory_human:1M\nused_memory_peak:1200000\n"
            "mem_fragmentation_ratio:1.1\nmaxmemory:10000000\nmaxmemory_policy:allkeys-lru\n"
            "evicted_keys:0\nexpired_keys:5\n"
        )
        result = await redis_memory(plugin, {})

        assert result.status == Status.HEALTHY
        assert result.data["usage_pct"] == 10.0
        assert result.data["maxmemory_policy"] == "allkeys-lru"

    @pytest.mark.asyncio
    async def test_high_usage_is_degraded(self):
        from mcp_linx.plugins.redis.tools import redis_memory

        plugin = _redis(
            "used_memory:950\nused_memory_peak:960\n"
            "mem_fragmentation_ratio:1.1\nmaxmemory:1000\nevicted_keys:0\n"
        )
        result = await redis_memory(plugin, {})

        assert result.status == Status.DEGRADED
        assert any("evictions/OOM" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_fragmentation_is_degraded(self):
        from mcp_linx.plugins.redis.tools import redis_memory

        plugin = _redis(
            "used_memory:100\nused_memory_peak:120\n"
            "mem_fragmentation_ratio:2.0\nmaxmemory:0\nevicted_keys:0\n"
        )
        result = await redis_memory(plugin, {})

        assert result.status == Status.DEGRADED
        assert any("аллокатор" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_cli_failure(self):
        from mcp_linx.plugins.redis.tools import redis_memory

        plugin = _redis("", returncode=1, stderr="Connection refused")
        result = await redis_memory(plugin, {})

        assert result.status == Status.ERROR
