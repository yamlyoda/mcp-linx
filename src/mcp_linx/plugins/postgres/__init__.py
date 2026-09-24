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
        # E4b: именованные таргеты (`plugins.postgres.targets.<имя>`) — свой
        # коннект (и, при ssh.tunnel, свой туннель) на каждый таргет.
        self._targets: dict[str, dict[str, Any]] = {}
        self._target_state: dict[str, dict[str, Any]] = {}

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
        raw_targets = config.get("targets", {})
        self._targets = (
            {name: dict(cfg) for name, cfg in raw_targets.items() if isinstance(cfg, dict)}
            if isinstance(raw_targets, dict)
            else {}
        )
        await self._connect_sync()

    def _target_config(self, name: str) -> dict[str, Any]:
        """Конфиг таргета: поля таргета поверх основных настроек плагина (E4b).

        Raises:
            KeyError: таргет не описан в `plugins.postgres.targets`.
        """
        if name not in self._targets:
            available = ", ".join(sorted(self._targets)) or "<none configured>"
            raise KeyError(f"Unknown PostgreSQL target '{name}'. Configured: {available}")
        return {**(self._config or {}), **self._targets[name]}

    async def _connection_for(self, host: str | None = None) -> Any:
        """Соединение для таргета (`host`) или primary (E4b).

        Соединения таргетов кэшируются: повторный вызов переиспользует коннект.
        """
        if not host:
            if not self._conn:
                await self._connect_sync()
            return self._conn

        name = str(host)
        state = self._target_state.get(name)
        if state is not None:
            return state["conn"]

        target_config = self._target_config(name)
        conn = await self._connect_target(target_config)
        self._target_state[name] = conn
        return conn["conn"]

    async def _connect_target(self, config: dict[str, Any]) -> dict[str, Any]:
        """Подключиться к таргету; при `ssh.tunnel` поднять туннель (E2/E4b)."""
        host = config.get("host", "localhost")
        port = int(config.get("port", 5432))
        tunnel: SSHTunnel | None = None
        pool: SSHConnectionPool | None = None

        ssh = config.get("ssh", {})
        if isinstance(ssh, dict) and ssh.get("tunnel"):
            if not ssh.get("host"):
                raise RuntimeError("ssh.tunnel requires ssh.host (SSH server to tunnel through)")
            pool = SSHConnectionPool()
            tunnel = SSHTunnel(pool.get(dict(ssh)), str(host), port)
            tunnel.start()
            host, port = tunnel.local_address

        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=config.get("database", "postgres"),
            user=config.get("user", "postgres"),
            **({"password": config["password"]} if config.get("password") else {}),
            **({"sslmode": config["ssl_mode"]} if config.get("ssl_mode") else {}),
        )
        conn.autocommit = True
        return {"conn": conn, "tunnel": tunnel, "pool": pool}

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
        # E4b: закрыть соединения/туннели всех таргетов
        for state in self._target_state.values():
            if state.get("conn") is not None:
                with suppress(Exception):
                    state["conn"].close()
            if state.get("tunnel") is not None:
                state["tunnel"].stop()
            if state.get("pool") is not None:
                state["pool"].close_all()
        self._target_state.clear()

    async def _execute_query(
        self,
        query: str,
        params: tuple[Any, ...] | None = None,
        host: str | None = None,
    ) -> list[dict[str, Any]]:
        """Выполнить SQL запрос и вернуть результат как список dict.

        `host` — имя таргета из `plugins.postgres.targets` (E4b); None = primary.
        """
        conn = await self._connection_for(host)

        with conn.cursor() as cur:
            cur.execute(query, params)

            if cur.description:
                columns = [desc[0] for desc in cur.description]
                rows = cur.fetchall()
                return [dict(zip(columns, row)) for row in rows]  # noqa: B905 — strict=False by design (len already equal)
            return []

    async def _execute_query_one(
        self,
        query: str,
        params: tuple[Any, ...] | None = None,
        host: str | None = None,
    ) -> dict[str, Any] | None:
        """Выполнить SQL запрос и вернуть одну строку (`host` — таргет, E4b)."""
        results = await self._execute_query(query, params, host=host)
        return results[0] if results else None
