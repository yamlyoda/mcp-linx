"""Integration tests: real services via docker compose (postgres, nginx, redis)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestPostgresIntegration:
    @pytest.mark.asyncio
    async def test_pg_connections(self, postgres_dsn):
        from mcp_linx.plugins.postgres import PostgresPlugin
        from mcp_linx.plugins.postgres.tools import pg_connections

        host, port = postgres_dsn
        plugin = PostgresPlugin()
        await plugin.initialize(
            {
                "host": host,
                "port": port,
                "database": "testdb",
                "user": "test",
                "password": "testpass",
                "ssl_mode": "disable",
            }
        )
        try:
            result = await pg_connections(plugin, {"limit": 10})
            assert result.status.value == "healthy"
            assert result.data["total"] >= 1  # как минимум собственное подключение
        finally:
            await plugin.destroy()

    @pytest.mark.asyncio
    async def test_pg_stats(self, postgres_dsn):
        from mcp_linx.plugins.postgres import PostgresPlugin
        from mcp_linx.plugins.postgres.tools import pg_stats

        host, port = postgres_dsn
        plugin = PostgresPlugin()
        await plugin.initialize(
            {
                "host": host,
                "port": port,
                "database": "testdb",
                "user": "test",
                "password": "testpass",
                "ssl_mode": "disable",
            }
        )
        try:
            result = await pg_stats(plugin, {})
            assert result.status.value == "healthy"
            assert "database" in result.data
            assert "tables" in result.data
            assert "indexes" in result.data
        finally:
            await plugin.destroy()

    @pytest.mark.asyncio
    async def test_pg_tables(self, postgres_dsn):
        from mcp_linx.plugins.postgres import PostgresPlugin
        from mcp_linx.plugins.postgres.tools import pg_tables

        host, port = postgres_dsn
        plugin = PostgresPlugin()
        await plugin.initialize(
            {
                "host": host,
                "port": port,
                "database": "testdb",
                "user": "test",
                "password": "testpass",
                "ssl_mode": "disable",
            }
        )
        try:
            result = await pg_tables(plugin, {"schema": "public"})
            assert result.status.value == "healthy"
            assert isinstance(result.data.get("tables"), list)
        finally:
            await plugin.destroy()


class TestNginxIntegration:
    @pytest.mark.asyncio
    async def test_nginx_stub_status_live(self, nginx_base_url):
        from mcp_linx.plugins.nginx import NginxPlugin
        from mcp_linx.plugins.nginx.tools import nginx_stub_status
        from mcp_linx.types import Status

        plugin = NginxPlugin()
        plugin._config = {"stub_status_url": f"{nginx_base_url}/nginx_status"}

        result = await nginx_stub_status(plugin, {})
        assert result.status == Status.HEALTHY
        assert "active_connections" in result.data
        assert "requests" in result.data

    @pytest.mark.asyncio
    async def test_nginx_root_returns_200(self, nginx_base_url):
        import httpx

        resp = httpx.get(f"{nginx_base_url}/", timeout=10)
        assert resp.status_code == 200
        assert "integration-ok" in resp.text


class TestRedisIntegration:
    @pytest.mark.asyncio
    async def test_redis_ping(self, redis_port, redis_cli_available):
        if not redis_cli_available:
            pytest.skip("redis-cli not installed on host — skipped")
        from mcp_linx.plugins.redis import RedisPlugin
        from mcp_linx.plugins.redis.tools import redis_ping
        from mcp_linx.types import Status

        plugin = RedisPlugin()
        await plugin.initialize(
            {
                "host": "127.0.0.1",
                "port": redis_port,
            }
        )

        try:
            result = await redis_ping(plugin, {})
            assert result.status == Status.HEALTHY
            assert result.data.get("reachable") is True
        finally:
            await plugin.destroy()

    @pytest.mark.asyncio
    async def test_redis_info_section(self, redis_port, redis_cli_available):
        if not redis_cli_available:
            pytest.skip("redis-cli not installed on host — skipped")
        from mcp_linx.plugins.redis import RedisPlugin
        from mcp_linx.plugins.redis.tools import redis_info

        plugin = RedisPlugin()
        await plugin.initialize(
            {
                "host": "127.0.0.1",
                "port": redis_port,
            }
        )
        try:
            result = await redis_info(plugin, {"section": "server"})
            assert result.status.value == "healthy"
            assert "info" in result.data
        finally:
            await plugin.destroy()
