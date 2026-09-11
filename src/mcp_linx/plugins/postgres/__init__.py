"""PostgreSQL плагин для MCP-Linx"""

from __future__ import annotations

from typing import Any

import psycopg2

from mcp_linx.plugins.base import DiagnosticPlugin, PluginTool
from mcp_linx.types import HealthStatus, PluginConfig, Status
from mcp_linx.types import ToolResult as ToolResult


class PostgresPlugin(DiagnosticPlugin):
    """Плагин для диагностики PostgreSQL"""

    id = "postgres"
    name = "PostgreSQL"
    description = (
        "Диагностика PostgreSQL: соединения, блокировки, медленные запросы, репликация, ресурсы"
    )
    version = "1.0.0"

    def __init__(self):
        self._conn = None
        self._config: PluginConfig | None = None

    def get_tools(self) -> list[PluginTool]:
        from mcp_linx.plugins.postgres.tools import (
            pg_activity,
            pg_connections,
            pg_locks,
            pg_replication,
            pg_slow_queries,
            pg_stats,
            pg_tables,
        )

        return [
            PluginTool("pg_connections", "Активные подключения к PostgreSQL", pg_connections),
            PluginTool("pg_locks", "Блокировки и заблокированные запросы", pg_locks),
            PluginTool(
                "pg_slow_queries", "Медленные запросы (pg_stat_statements)", pg_slow_queries
            ),
            PluginTool(
                "pg_activity",
                "Полная активность: текущие запросы, состояния, ожидания",
                pg_activity,
            ),
            PluginTool("pg_stats", "Статистика: таблицы, индексы, базы данных", pg_stats),
            PluginTool("pg_replication", "Статус репликации (если настроена)", pg_replication),
            PluginTool("pg_tables", "Список таблиц с размерами и статистикой", pg_tables),
        ]

    async def initialize(self, config: PluginConfig) -> None:
        self._config = config
        await self._connect_sync()

    async def _connect_sync(self) -> None:
        """Синхронное подключение к PostgreSQL"""
        config = self._config or {}

        host = config.get("host", "localhost")
        port = int(config.get("port", 5432))
        database = config.get("database", "postgres")
        user = config.get("user", "postgres")
        password = config.get("password", "")
        ssl_mode = config.get("ssl_mode", "prefer")

        conn_params: dict[str, Any] = {
            "host": host,
            "port": port,
            "database": database,
            "user": user,
        }

        if password:
            conn_params["password"] = password

        if ssl_mode:
            conn_params["sslmode"] = ssl_mode

        self._conn = psycopg2.connect(**conn_params)
        self._conn.autocommit = True

    async def health_check(self) -> HealthStatus:
        try:
            if not self._conn:
                await self._connect_sync()

            with self._conn.cursor() as cur:
                cur.execute("SELECT 1")
                result = cur.fetchone()

            if result and result[0] == 1:
                return HealthStatus(Status.HEALTHY, "PostgreSQL is reachable and accepting queries")
            return HealthStatus(Status.UNHEALTHY, "PostgreSQL health check failed")
        except Exception as e:
            return HealthStatus(Status.ERROR, f"Health check failed: {e}")

    async def destroy(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    async def _execute_query(self, query: str, params: tuple | None = None) -> list[dict[str, Any]]:
        """Выполнить SQL запрос и вернуть результат как список dict"""
        if not self._conn:
            await self._connect_sync()

        with self._conn.cursor() as cur:
            cur.execute(query, params)

            if cur.description:
                columns = [desc[0] for desc in cur.description]
                rows = cur.fetchall()
                return [dict(zip(columns, row)) for row in rows]  # noqa: B905 — strict=False by design (len already equal)
            return []

    async def _execute_query_one(
        self, query: str, params: tuple | None = None
    ) -> dict[str, Any] | None:
        """Выполнить SQL запрос и вернуть одну строку"""
        results = await self._execute_query(query, params)
        return results[0] if results else None
