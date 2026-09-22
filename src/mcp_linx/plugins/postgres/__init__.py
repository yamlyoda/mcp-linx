"""PostgreSQL плагин для MCP-Linx"""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any

import psycopg2

from mcp_linx.adapters.ssh_pool import SSHConnectionPool, SSHTunnel
from mcp_linx.plugins.base import DiagnosticPlugin, PluginTool
from mcp_linx.types import HealthStatus, PluginConfig, Status
from mcp_linx.types import ToolResult as ToolResult

logger = logging.getLogger(__name__)


class PostgresPlugin(DiagnosticPlugin):
    """Плагин для диагностики PostgreSQL"""

    id = "postgres"
    name = "PostgreSQL"
    description = (
        "Диагностика PostgreSQL: соединения, блокировки, медленные запросы, репликация, ресурсы"
    )
    version = "1.0.0"

    def __init__(self) -> None:
        self._conn: Any = None
        self._config: PluginConfig | None = None
        self._tunnel: SSHTunnel | None = None
        self._ssh_pool: SSHConnectionPool | None = None

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
        config: dict[str, Any] = self._config or {}

        host = config.get("host", "localhost")
        port = int(config.get("port", 5432))
        database = config.get("database", "postgres")
        user = config.get("user", "postgres")
        password = config.get("password", "")
        ssl_mode = config.get("ssl_mode", "prefer")

        host, port = self._maybe_start_tunnel(config, host, port)

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

    def _maybe_start_tunnel(self, config: dict[str, Any], host: Any, port: int) -> tuple[Any, int]:
        """Поднять SSH-туннель к PostgreSQL, если он запрошен (E2).

        Включается явно: `plugins.postgres.ssh.tunnel: true` вместе с
        `plugins.postgres.ssh.host`. Возвращает адрес, к которому подключаться.

        Raises:
            RuntimeError: туннель запрошен, но `ssh.host` не задан.
        """
        ssh = config.get("ssh", {})
        if not isinstance(ssh, dict) or not ssh.get("tunnel"):
            return host, port
        if not ssh.get("host"):
            raise RuntimeError("ssh.tunnel requires ssh.host (SSH server to tunnel through)")

        self._ssh_pool = SSHConnectionPool()
        client = self._ssh_pool.get(dict(ssh))
        self._tunnel = SSHTunnel(client, str(host), port)
        self._tunnel.start()
        local_host, local_port = self._tunnel.local_address
        logger.info(f"PostgreSQL via SSH tunnel {local_host}:{local_port} -> {host}:{port}")
        return local_host, local_port

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
            with suppress(Exception):
                self._conn.close()
            self._conn = None
        if self._tunnel is not None:
            self._tunnel.stop()
            self._tunnel = None
        if self._ssh_pool is not None:
            self._ssh_pool.close_all()
            self._ssh_pool = None

    async def _execute_query(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> list[dict[str, Any]]:
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
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> dict[str, Any] | None:
        """Выполнить SQL запрос и вернуть одну строку"""
        results = await self._execute_query(query, params)
        return results[0] if results else None
