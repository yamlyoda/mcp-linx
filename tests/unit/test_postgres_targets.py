"""Wave 13 (E4b): именованные таргеты PostgreSQL (`plugins.postgres.targets`).

Проверяем резолв соединения по имени таргета, кэширование, туннель на таргет,
очистку в `destroy()` и проброс `host` из tools. Сети и БД нет.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import mcp_linx.plugins.postgres as mod


class _FakeTunnel:
    instances: list[_FakeTunnel] = []

    def __init__(self, client: Any, remote_host: str, remote_port: int) -> None:
        self.remote = (remote_host, remote_port)
        self.started = False
        self.stopped = False
        type(self).instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    @property
    def local_address(self) -> tuple[str, int]:
        return "127.0.0.1", 15432


class _FakePool:
    instances: list[_FakePool] = []

    def __init__(self) -> None:
        self.closed = False
        type(self).instances.append(self)

    def get(self, config: dict[str, Any]) -> str:
        return "client-sentinel"

    def close_all(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset():
    _FakeTunnel.instances.clear()
    _FakePool.instances.clear()


@pytest.fixture()
def connections(monkeypatch):
    """Перехват psycopg2.connect: список kwargs и объекты-коннекты."""
    captured: list[dict[str, Any]] = []
    conns: list[MagicMock] = []

    def fake_connect(**kwargs: Any) -> MagicMock:
        captured.append(kwargs)
        conn = MagicMock()
        conns.append(conn)
        return conn

    monkeypatch.setattr(mod.psycopg2, "connect", fake_connect)
    monkeypatch.setattr(mod, "SSHTunnel", _FakeTunnel)
    monkeypatch.setattr(mod, "SSHConnectionPool", _FakePool)
    return captured, conns


PRIMARY = {"host": "primary.db", "port": 5432, "password": "pw", "ssl_mode": "prefer"}


class TestTargetConfig:
    @pytest.mark.asyncio
    async def test_target_overrides_primary_fields(self, connections):
        plugin = mod.PostgresPlugin()
        await plugin.initialize({**PRIMARY, "targets": {"replica": {"host": "replica.db"}}})

        config = plugin._target_config("replica")

        assert config["host"] == "replica.db"
        assert config["password"] == "pw"  # унаследовано от primary
        assert plugin._targets == {"replica": {"host": "replica.db"}}

    @pytest.mark.asyncio
    async def test_unknown_target_lists_configured(self, connections):
        plugin = mod.PostgresPlugin()
        await plugin.initialize({**PRIMARY, "targets": {"replica": {"host": "r.db"}}})

        with pytest.raises(KeyError, match="replica"):
            plugin._target_config("ghost")

    @pytest.mark.asyncio
    async def test_non_dict_targets_are_ignored(self, connections):
        plugin = mod.PostgresPlugin()
        await plugin.initialize({**PRIMARY, "targets": {"broken": "not-a-dict"}})

        assert plugin._targets == {}


class TestConnectionResolution:
    @pytest.mark.asyncio
    async def test_primary_used_without_host(self, connections):
        captured, _conns = connections
        plugin = mod.PostgresPlugin()
        await plugin.initialize(PRIMARY)

        conn = await plugin._connection_for(None)

        assert conn is plugin._conn
        assert captured[0]["host"] == "primary.db"
        assert len(captured) == 1  # повторных подключений нет

    @pytest.mark.asyncio
    async def test_target_uses_own_host_and_is_cached(self, connections):
        captured, conns = connections
        plugin = mod.PostgresPlugin()
        await plugin.initialize({**PRIMARY, "targets": {"replica": {"host": "replica.db"}}})

        first = await plugin._connection_for("replica")
        second = await plugin._connection_for("replica")

        assert first is second is conns[-1]
        assert captured[-1]["host"] == "replica.db"
        assert captured[-1]["port"] == 5432
        assert len(captured) == 2  # primary + один таргет

    @pytest.mark.asyncio
    async def test_target_with_tunnel_connects_to_local_address(self, connections):
        captured, _conns = connections
        plugin = mod.PostgresPlugin()
        await plugin.initialize(
            {
                **PRIMARY,
                "targets": {
                    "behind-bastion": {
                        "host": "internal.db",
                        "ssh": {"host": "bastion", "tunnel": True},
                    }
                },
            }
        )

        await plugin._connection_for("behind-bastion")

        tunnel = _FakeTunnel.instances[-1]
        assert tunnel.started is True
        assert tunnel.remote == ("internal.db", 5432)
        assert captured[-1]["host"] == "127.0.0.1"
        assert captured[-1]["port"] == 15432

    @pytest.mark.asyncio
    async def test_target_tunnel_without_ssh_host_fails(self, connections):
        plugin = mod.PostgresPlugin()
        await plugin.initialize({**PRIMARY, "targets": {"broken": {"ssh": {"tunnel": True}}}})

        with pytest.raises(RuntimeError, match="ssh.host"):
            await plugin._connection_for("broken")


class TestDestroy:
    @pytest.mark.asyncio
    async def test_closes_target_connections_tunnels_and_pools(self, connections):
        plugin = mod.PostgresPlugin()
        await plugin.initialize(
            {
                **PRIMARY,
                "targets": {
                    "via-bastion": {
                        "host": "internal.db",
                        "ssh": {"host": "bastion", "tunnel": True},
                    }
                },
            }
        )
        target_conn = await plugin._connection_for("via-bastion")

        await plugin.destroy()

        target_conn.close.assert_called_once()
        assert _FakeTunnel.instances[-1].stopped is True
        assert _FakePool.instances[-1].closed is True
        assert plugin._target_state == {}


class TestToolHostPassThrough:
    @pytest.mark.asyncio
    async def test_pg_connections_forwards_host(self):
        from mcp_linx.plugins.postgres.tools import pg_connections

        plugin = MagicMock()
        plugin._execute_query = AsyncMock(return_value=[])

        await pg_connections(plugin, {"host": "replica"})

        assert plugin._execute_query.await_args.kwargs["host"] == "replica"

    @pytest.mark.asyncio
    async def test_pg_tables_forwards_host_and_schema(self):
        from mcp_linx.plugins.postgres.tools import pg_tables

        plugin = MagicMock()
        plugin._execute_query = AsyncMock(return_value=[])

        await pg_tables(plugin, {"host": "replica", "schema": "public"})

        assert plugin._execute_query.await_args.kwargs["host"] == "replica"
        assert plugin._execute_query.await_args.args[1] == ("public",)

    @pytest.mark.asyncio
    async def test_pg_replication_forwards_host(self):
        from mcp_linx.plugins.postgres.tools import pg_replication

        plugin = MagicMock()
        plugin._execute_query_one = AsyncMock(return_value={"is_in_recovery": False})
        plugin._execute_query = AsyncMock(return_value=[])

        await pg_replication(plugin, {"host": "replica"})

        assert plugin._execute_query_one.await_args.kwargs["host"] == "replica"
