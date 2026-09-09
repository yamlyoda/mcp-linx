"""Unit tests part 3: postgres tools"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_plugin(plugin_class, methods: dict):
    plugin = MagicMock(spec=plugin_class)
    for name, ret in methods.items():
        setattr(plugin, name, AsyncMock(return_value=ret))
    return plugin


class TestPostgresTools:
    @pytest.mark.asyncio
    async def test_pg_connections_ok(self):
        from mcp_linx.plugins.postgres import PostgresPlugin
        from mcp_linx.plugins.postgres.tools import pg_connections
        from mcp_linx.types import Status

        plugin = _make_plugin(PostgresPlugin, {
            "_execute_query": [{"state": "active"}, {"state": "idle"}],
        })
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
