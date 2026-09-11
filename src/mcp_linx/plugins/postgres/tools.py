"""Инструменты PostgreSQL плагина"""

from __future__ import annotations

from typing import Any

from psycopg2 import sql

from mcp_linx.plugins.postgres import PostgresPlugin
from mcp_linx.types import ToolResult


async def pg_stats(plugin: PostgresPlugin, params: dict[str, Any]) -> ToolResult:
    """Статистика: таблицы, индексы, базы данных"""
    try:
        results: dict[str, Any] = {}

        db_stats = await plugin._execute_query("""
            SELECT
                datname, pg_size_pretty(pg_database_size(datname)) AS size,
                numbackends, xact_commit, xact_rollback,
                tup_returned, tup_fetched, tup_inserted, tup_updated, tup_deleted
            FROM pg_stat_database
            WHERE datname = current_database()
        """)
        results["database"] = db_stats

        table_stats = await plugin._execute_query("""
            SELECT
                schemaname, relname AS table_name,
                n_live_tup, n_dead_tup, n_mod_since_analyze,
                last_vacuum, last_autovacuum, last_analyze, last_autoanalyze,
                pg_size_pretty(pg_total_relation_size((schemaname || '.' || relname)::regclass)) AS size
            FROM pg_stat_user_tables
            ORDER BY n_live_tup DESC
            LIMIT 20;
        """)
        results["tables"] = table_stats

        index_stats = await plugin._execute_query("""
            SELECT
                schemaname, relname AS table_name, indexrelname AS index_name,
                idx_scan, idx_tup_read, idx_tup_fetch
            FROM pg_stat_user_indexes
            ORDER BY idx_scan DESC
            LIMIT 20;
        """)
        results["indexes"] = index_stats

        return ToolResult.ok(results)
    except Exception as e:
        return ToolResult.error(f"Failed to get stats: {e}")


async def pg_replication(plugin: PostgresPlugin, params: dict[str, Any]) -> ToolResult:
    """Статус репликации (если настроена)"""
    try:
        is_primary = await plugin._execute_query_one("SELECT pg_is_in_recovery() AS is_in_recovery;")

        if is_primary and is_primary.get("is_in_recovery"):
            replication_query = """
            SELECT client_addr, client_hostname, client_port, pid AS writer_pid,
                   status, replication_lag_bytes, replication_lag_time
            FROM pg_stat_replication;
            """
            status = await plugin._execute_query(replication_query)
            return ToolResult.ok({"role": "standby", "replication_status": status, "is_in_recovery": True})
        else:
            replication_query = """
            SELECT client_addr, client_hostname, client_port, pid AS writer_pid,
                   status, sent_lsn, write_lsn, flush_lsn, replay_lsn,
                   sent_lag_bytes, write_lag_bytes, flush_lag_bytes, replay_lag_bytes
            FROM pg_stat_replication;
            """
            status = await plugin._execute_query(replication_query)
            return ToolResult.ok({"role": "primary", "replication_status": status, "is_in_recovery": False})
    except Exception as e:
        return ToolResult.error(f"Failed to get replication status: {e}")



async def pg_activity(plugin: PostgresPlugin, params: dict[str, Any]) -> ToolResult:
    """Полная активность: текущие запросы, состояния, ожидания"""
    try:
        activity_query = """
        SELECT
            pid, usename, datname, application_name,
            client_addr, client_hostname, client_port,
            backend_start, xact_start, query_start, state_change,
            state, wait_event_type, wait_event, query
        FROM pg_stat_activity
        ORDER BY query_start;
        """

        activity = await plugin._execute_query(activity_query)

        total = len(activity)
        active = sum(1 for a in activity if a.get("state") == "active")
        idle = sum(1 for a in activity if a.get("state") == "idle")
        idle_in_transaction = sum(1 for a in activity if a.get("state") == "idle in transaction")
        waiting = sum(1 for a in activity if a.get("wait_event_type") == "Lock")

        return ToolResult.ok({
            "activity": activity,
            "total": total,
            "active": active,
            "idle": idle,
            "idle_in_transaction": idle_in_transaction,
            "waiting": waiting,
        })
    except Exception as e:
        return ToolResult.error(f"Failed to get activity: {e}")


async def pg_connections(plugin: PostgresPlugin, params: dict[str, Any]) -> ToolResult:
    """Активные подключения к PostgreSQL"""
    try:
        query = """
        SELECT
            pid, usename, datname, application_name, client_addr, client_hostname,
            client_port, backend_start, xact_start, query_start, state_change,
            state, backend_xid, backend_xmin, query, wait_event_type, wait_event
        FROM pg_stat_activity
        ORDER BY query_start;
        """

        connections = await plugin._execute_query(query)

        total = len(connections)
        active = sum(1 for c in connections if c.get("state") not in ("idle", "idle in transaction"))
        idle = sum(1 for c in connections if c.get("state") == "idle")
        idle_in_transaction = sum(1 for c in connections if c.get("state") == "idle in transaction")

        return ToolResult.ok({
            "connections": connections,
            "total": total,
            "active": active,
            "idle": idle,
            "idle_in_transaction": idle_in_transaction,
            "summary": {
                "total_connections": total,
                "active_queries": active,
                "idle_connections": idle,
                "idle_in_transaction": idle_in_transaction,
            },
        })
    except Exception as e:
        return ToolResult.error(f"Failed to get connections: {e}")


async def pg_locks(plugin: PostgresPlugin, params: dict[str, Any]) -> ToolResult:
    """Блокировки и заблокированные запросы"""
    try:
        locks_query = """
        SELECT
            l.pid, l.mode, l.granted, l.locktype,
            l.database, l.relation, l.page, l_tuple, l.virtualxid,
            l.transactionid, l.classid, l.objid, l.objsubid,
            a.usename, a.datname, a.query, a.state, a.wait_event_type, a.wait_event
        FROM pg_locks l
        LEFT JOIN pg_stat_activity a ON l.pid = a.pid
        ORDER BY l.pid, l.mode;
        """

        all_locks = await plugin._execute_query(locks_query)

        blocked_locks = [l for l in all_locks if not l.get("granted")]

        blocking_info = []
        for blocked in blocked_locks:
            blocking_query = f"""
            SELECT
                l2.pid AS blocking_pid,
                l2.mode AS blocking_mode,
                a2.query AS blocking_query,
                a2.state AS blocking_state,
                a2.usename AS blocking_user
            FROM pg_locks l2
            JOIN pg_stat_activity a2 ON l2.pid = a2.pid
            WHERE l2.granted = true
              AND l2.pid != {blocked['pid']}
            LIMIT 1;
            """
            blocking = await plugin._execute_query(blocking_query)
            if blocking:
                blocking_info.append({
                    "blocked_pid": blocked["pid"],
                    "blocked_mode": blocked["mode"],
                    "blocking_pid": blocking[0]["blocking_pid"],
                    "blocking_query": blocking[0]["blocking_query"],
                    "blocking_state": blocking[0]["blocking_state"],
                    "blocking_user": blocking[0]["blocking_user"],
                })

        return ToolResult.ok({
            "all_locks": all_locks,
            "blocked_locks": blocked_locks,
            "blocking_info": blocking_info,
            "summary": {
                "total_locks": len(all_locks),
                "blocked_locks_count": len(blocked_locks),
                "blocking_processes_count": len(blocking_info),
            },
        })
    except Exception as e:
        return ToolResult.error(f"Failed to get locks: {e}")


async def pg_tables(plugin: PostgresPlugin, params: dict[str, Any]) -> ToolResult:
    """Список таблиц с размерами и статистикой"""
    try:
        schema = params.get("schema", "public")

        # Validate schema against allowlist of valid PostgreSQL identifiers
        valid_schemas = {"public", "pg_catalog", "information_schema"}
        if schema not in valid_schemas:
            return ToolResult.error(
                f"Invalid schema '{schema}'. Allowed: public, pg_catalog, information_schema"
            )

        query = sql.SQL("""
            SELECT
                schemaname, relname AS table_name,
                n_live_tup AS rows_count, n_dead_tup AS dead_rows,
                n_mod_since_analyze AS unanalyzed_changes,
                pg_size_pretty(pg_relation_size(schemaname || '.' || relname)) AS size,
                pg_size_pretty(pg_total_relation_size(schemaname || '.' || relname)) AS total_size,
                last_vacuum, last_autovacuum, last_analyze, last_autoanalyze,
                vacuum_count, autovacuum_count, analyze_count, autoanalyze_count
            FROM pg_stat_user_tables
            WHERE schemaname = %s
            ORDER BY n_live_tup DESC
            LIMIT 50;
        """)

        tables = await plugin._execute_query(query, (schema,))

        needs_vacuum = [
            t for t in tables
            if t.get("dead_rows", 0) > 1000 or t.get("unanalyzed_changes", 0) > 10000
        ]

        return ToolResult.ok({
            "tables": tables,
            "schema": schema,
            "count": len(tables),
            "needs_vacuum": needs_vacuum,
        })
    except Exception as e:
        return ToolResult.error(f"Failed to get tables: {e}")


async def pg_slow_queries(plugin: PostgresPlugin, params: dict[str, Any]) -> ToolResult:
    """Медленные запросы из pg_stat_statements"""
    try:
        threshold_ms = int(params.get("threshold_ms", 1000))
        limit = min(int(params.get("limit", 20)), 100)

        query = f"""
        SELECT
            query, calls, total_exec_time, mean_exec_time,
            min_exec_time, max_exec_time, rows,
            shared_blks_hit, shared_blks_read, shared_blks_written
        FROM pg_stat_statements
        WHERE mean_exec_time > {threshold_ms}
        ORDER BY mean_exec_time DESC
        LIMIT {limit};
        """

        slow_queries = await plugin._execute_query(query)

        return ToolResult.ok({
            "slow_queries": slow_queries,
            "threshold_ms": threshold_ms,
            "count": len(slow_queries),
        })
    except Exception as e:
        return ToolResult.error(f"Failed to get slow queries: {e}")

