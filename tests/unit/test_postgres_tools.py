"""Unit tests for PostgreSQL diagnostic tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from conftest import make_plugin as _make_plugin


class TestPostgresDiagnosticTools:
    @pytest.mark.asyncio
    async def test_pg_stats_collects_database_tables_and_indexes(self):
        from mcp_linx.plugins.postgres import PostgresPlugin
        from mcp_linx.plugins.postgres.tools import pg_stats
        from mcp_linx.types import Status

        plugin = _make_plugin(PostgresPlugin, {})
        plugin._execute_query = AsyncMock(
            side_effect=[
                [{"datname": "app", "size": "20 MB"}],
                [{"table_name": "orders", "n_live_tup": 100}],
                [{"index_name": "orders_pkey", "idx_scan": 50}],
            ]
        )

        result = await pg_stats(plugin, {"host": "replica"})

        assert result.status == Status.HEALTHY
        assert result.data == {
            "database": [{"datname": "app", "size": "20 MB"}],
            "tables": [{"table_name": "orders", "n_live_tup": 100}],
            "indexes": [{"index_name": "orders_pkey", "idx_scan": 50}],
        }
        assert all(
            call.kwargs["host"] == "replica" for call in plugin._execute_query.await_args_list
        )

    @pytest.mark.asyncio
    async def test_pg_stats_wraps_database_failure(self):
        from mcp_linx.plugins.postgres import PostgresPlugin
        from mcp_linx.plugins.postgres.tools import pg_stats
        from mcp_linx.types import Status

        plugin = _make_plugin(PostgresPlugin, {})
        plugin._execute_query = AsyncMock(side_effect=RuntimeError("database offline"))

        result = await pg_stats(plugin, {})

        assert result.status == Status.ERROR
        assert result.error_message == "Failed to get stats: database offline"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("is_in_recovery", "role"),
        [(True, "standby"), (False, "primary"), (None, "primary")],
    )
    async def test_pg_replication_reports_role(self, is_in_recovery, role):
        from mcp_linx.plugins.postgres import PostgresPlugin
        from mcp_linx.plugins.postgres.tools import pg_replication
        from mcp_linx.types import Status

        plugin = _make_plugin(PostgresPlugin, {})
        plugin._execute_query_one = AsyncMock(return_value={"is_in_recovery": is_in_recovery})
        plugin._execute_query = AsyncMock(return_value=[{"writer_pid": 42}])

        result = await pg_replication(plugin, {})

        assert result.status == Status.HEALTHY
        assert result.data["role"] == role
        assert result.data["replication_status"] == [{"writer_pid": 42}]

    @pytest.mark.asyncio
    async def test_pg_replication_wraps_failure(self):
        from mcp_linx.plugins.postgres import PostgresPlugin
        from mcp_linx.plugins.postgres.tools import pg_replication
        from mcp_linx.types import Status

        plugin = _make_plugin(PostgresPlugin, {"_execute_query_one": None})
        plugin._execute_query_one = AsyncMock(
            side_effect=RuntimeError("recovery state unavailable")
        )

        result = await pg_replication(plugin, {})

        assert result.status == Status.ERROR
        assert "replication status" in result.error_message

    @pytest.mark.asyncio
    async def test_pg_activity_summarizes_states_and_waits(self):
        from mcp_linx.plugins.postgres import PostgresPlugin
        from mcp_linx.plugins.postgres.tools import pg_activity
        from mcp_linx.types import Status

        rows = [
            {"pid": 1, "state": "active", "wait_event_type": "Lock"},
            {"pid": 2, "state": "idle"},
            {"pid": 3, "state": "idle in transaction"},
            {"pid": 4, "state": "active"},
        ]
        plugin = _make_plugin(PostgresPlugin, {"_execute_query": rows})

        result = await pg_activity(plugin, {"host": "primary"})

        assert result.status == Status.HEALTHY
        assert result.data == {
            "activity": rows,
            "total": 4,
            "active": 2,
            "idle": 1,
            "idle_in_transaction": 1,
            "waiting": 1,
        }
        assert plugin._execute_query.await_args.kwargs["host"] == "primary"

    @pytest.mark.asyncio
    async def test_pg_activity_wraps_failure(self):
        from mcp_linx.plugins.postgres import PostgresPlugin
        from mcp_linx.plugins.postgres.tools import pg_activity
        from mcp_linx.types import Status

        plugin = _make_plugin(PostgresPlugin, {})
        plugin._execute_query = AsyncMock(side_effect=RuntimeError("query failed"))

        result = await pg_activity(plugin, {})

        assert result.status == Status.ERROR
        assert result.error_message == "Failed to get activity: query failed"

    @pytest.mark.asyncio
    async def test_pg_connections_summary_and_failure(self):
        from mcp_linx.plugins.postgres import PostgresPlugin
        from mcp_linx.plugins.postgres.tools import pg_connections
        from mcp_linx.types import Status

        rows = [
            {"pid": 1, "state": "active"},
            {"pid": 2, "state": "idle"},
            {"pid": 3, "state": "idle in transaction"},
        ]
        plugin = _make_plugin(PostgresPlugin, {"_execute_query": rows})

        result = await pg_connections(plugin, {})

        assert result.status == Status.HEALTHY
        assert result.data["summary"] == {
            "total_connections": 3,
            "active_queries": 1,
            "idle_connections": 1,
            "idle_in_transaction": 1,
        }

        plugin._execute_query.side_effect = RuntimeError("connection reset")
        failed = await pg_connections(plugin, {})
        assert failed.status == Status.ERROR
        assert failed.error_message == "Failed to get connections: connection reset"

    @pytest.mark.asyncio
    async def test_pg_locks_joins_blocking_process(self):
        from mcp_linx.plugins.postgres import PostgresPlugin
        from mcp_linx.plugins.postgres.tools import pg_locks
        from mcp_linx.types import Status

        granted = {"pid": 1, "mode": "AccessExclusiveLock", "granted": True}
        blocked = {"pid": 2, "mode": "RowExclusiveLock", "granted": False}
        blocker = {
            "blocking_pid": 1,
            "blocking_mode": "AccessExclusiveLock",
            "blocking_query": "UPDATE orders SET ...",
            "blocking_state": "idle in transaction",
            "blocking_user": "app",
        }
        plugin = _make_plugin(PostgresPlugin, {})
        plugin._execute_query = AsyncMock(side_effect=[[granted, blocked], [blocker]])

        result = await pg_locks(plugin, {"host": "primary"})

        assert result.status == Status.HEALTHY
        assert result.data["blocked_locks"] == [blocked]
        assert result.data["blocking_info"][0]["blocked_pid"] == 2
        assert result.data["blocking_info"][0]["blocking_pid"] == 1
        assert result.data["summary"] == {
            "total_locks": 2,
            "blocked_locks_count": 1,
            "blocking_processes_count": 1,
        }
        assert plugin._execute_query.await_args_list[1].args[1] == (2,)

    @pytest.mark.asyncio
    async def test_pg_locks_ignores_unmatched_blocker_and_wraps_failure(self):
        from mcp_linx.plugins.postgres import PostgresPlugin
        from mcp_linx.plugins.postgres.tools import pg_locks
        from mcp_linx.types import Status

        plugin = _make_plugin(PostgresPlugin, {})
        plugin._execute_query = AsyncMock(side_effect=[[{"pid": 2, "granted": False}], []])

        result = await pg_locks(plugin, {})

        assert result.status == Status.HEALTHY
        assert result.data["blocking_info"] == []

        plugin._execute_query.side_effect = RuntimeError("locks unavailable")
        failed = await pg_locks(plugin, {})
        assert failed.status == Status.ERROR
        assert failed.error_message == "Failed to get locks: locks unavailable"

    @pytest.mark.asyncio
    async def test_pg_tables_flags_vacuum_work_and_wraps_failure(self):
        from mcp_linx.plugins.postgres import PostgresPlugin
        from mcp_linx.plugins.postgres.tools import pg_tables
        from mcp_linx.types import Status

        rows = [
            {"table_name": "dead", "dead_rows": 1001, "unanalyzed_changes": 0},
            {"table_name": "stale_stats", "dead_rows": 0, "unanalyzed_changes": 10001},
            {"table_name": "healthy", "dead_rows": 5, "unanalyzed_changes": 2},
        ]
        plugin = _make_plugin(PostgresPlugin, {"_execute_query": rows})

        result = await pg_tables(plugin, {"schema": "information_schema", "host": "analytics"})

        assert result.status == Status.HEALTHY
        assert result.data["count"] == 3
        assert [table["table_name"] for table in result.data["needs_vacuum"]] == [
            "dead",
            "stale_stats",
        ]
        assert plugin._execute_query.await_args.args[1] == ("information_schema",)
        assert plugin._execute_query.await_args.kwargs["host"] == "analytics"

        plugin._execute_query.side_effect = RuntimeError("catalog unavailable")
        failed = await pg_tables(plugin, {})
        assert failed.status == Status.ERROR
        assert failed.error_message == "Failed to get tables: catalog unavailable"

    @pytest.mark.asyncio
    async def test_pg_tables_rejects_non_allowlisted_schema(self):
        from mcp_linx.plugins.postgres import PostgresPlugin
        from mcp_linx.plugins.postgres.tools import pg_tables
        from mcp_linx.types import Status

        plugin = MagicMock(spec=PostgresPlugin)
        plugin._execute_query = AsyncMock()

        result = await pg_tables(plugin, {"schema": "pg_toast"})

        assert result.status == Status.ERROR
        assert "Allowed: public, pg_catalog, information_schema" in result.error_message
        plugin._execute_query.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pg_slow_queries_caps_limit_and_wraps_failure(self):
        from mcp_linx.plugins.postgres import PostgresPlugin
        from mcp_linx.plugins.postgres.tools import pg_slow_queries
        from mcp_linx.types import Status

        plugin = _make_plugin(PostgresPlugin, {"_execute_query": [{"query": "SELECT pg_sleep(2)"}]})

        result = await pg_slow_queries(
            plugin, {"threshold_ms": 250, "limit": 500, "host": "primary"}
        )

        assert result.status == Status.HEALTHY
        assert result.data["count"] == 1
        assert result.data["threshold_ms"] == 250
        assert plugin._execute_query.await_args.args[1] == (250, 100)

        plugin._execute_query.side_effect = RuntimeError("pg_stat_statements unavailable")
        failed = await pg_slow_queries(plugin, {"threshold_ms": "not-a-number"})
        assert failed.status == Status.ERROR
        assert "Failed to get slow queries" in failed.error_message
