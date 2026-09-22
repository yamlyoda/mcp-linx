"""Wave 10 (E2): PostgreSQL через SSH-туннель — wiring плагина.

`SSHTunnel` и `SSHConnectionPool` подменяются: проверяем, что при
`ssh.tunnel: true` подключение идёт на локальный адрес туннеля, а `destroy()`
останавливает туннель и закрывает пул. Реальных SSH/БД нет.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

import mcp_linx.plugins.postgres as mod


class _FakeTunnel:
    instances: list[_FakeTunnel] = []

    def __init__(self, client: Any, remote_host: str, remote_port: int) -> None:
        self.client = client
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
        self.requested: list[dict[str, Any]] = []
        self.closed = False
        type(self).instances.append(self)

    def get(self, config: dict[str, Any]) -> str:
        self.requested.append(config)
        return "client-sentinel"

    def close_all(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_fakes():
    _FakeTunnel.instances.clear()
    _FakePool.instances.clear()


def _install(monkeypatch) -> dict[str, Any]:
    """Подменить psycopg2.connect, SSHTunnel и пул; вернуть перехваченные параметры."""
    captured: dict[str, Any] = {}

    def fake_connect(**kwargs: Any) -> MagicMock:
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(mod.psycopg2, "connect", fake_connect)
    monkeypatch.setattr(mod, "SSHTunnel", _FakeTunnel)
    monkeypatch.setattr(mod, "SSHConnectionPool", _FakePool)
    return captured


class TestWithoutTunnel:
    @pytest.mark.asyncio
    async def test_direct_connection_unchanged(self, monkeypatch):
        captured = _install(monkeypatch)
        plugin = mod.PostgresPlugin()

        await plugin.initialize({"host": "db.internal", "port": 5432})

        assert captured["host"] == "db.internal"
        assert captured["port"] == 5432
        assert plugin._tunnel is None
        assert plugin._ssh_pool is None

    @pytest.mark.asyncio
    async def test_tunnel_false_does_not_start_tunnel(self, monkeypatch):
        captured = _install(monkeypatch)
        plugin = mod.PostgresPlugin()

        await plugin.initialize({"host": "db", "ssh": {"host": "bastion", "tunnel": False}})

        assert captured["host"] == "db"
        assert _FakeTunnel.instances == []


class TestWithTunnel:
    @pytest.mark.asyncio
    async def test_connects_to_local_tunnel_address(self, monkeypatch):
        captured = _install(monkeypatch)
        plugin = mod.PostgresPlugin()

        await plugin.initialize(
            {
                "host": "db.internal",
                "port": 5432,
                "ssh": {"host": "bastion", "username": "ops", "tunnel": True},
            }
        )

        assert captured["host"] == "127.0.0.1"
        assert captured["port"] == 15432
        tunnel = _FakeTunnel.instances[-1]
        assert tunnel.started is True
        assert tunnel.remote == ("db.internal", 5432)
        assert _FakePool.instances[-1].requested == [
            {"host": "bastion", "username": "ops", "tunnel": True}
        ]

    @pytest.mark.asyncio
    async def test_destroy_stops_tunnel_and_closes_pool(self, monkeypatch):
        _install(monkeypatch)
        plugin = mod.PostgresPlugin()
        await plugin.initialize({"host": "db", "ssh": {"host": "bastion", "tunnel": True}})

        await plugin.destroy()

        assert _FakeTunnel.instances[-1].stopped is True
        assert _FakePool.instances[-1].closed is True
        assert plugin._tunnel is None
        assert plugin._ssh_pool is None

    @pytest.mark.asyncio
    async def test_tunnel_without_ssh_host_fails_fast(self, monkeypatch):
        _install(monkeypatch)
        plugin = mod.PostgresPlugin()

        with pytest.raises(RuntimeError, match="ssh.host"):
            await plugin.initialize({"host": "db", "ssh": {"tunnel": True}})

        assert _FakeTunnel.instances == []

    @pytest.mark.asyncio
    async def test_ssl_mode_passed_to_libpq_with_tunnel(self, monkeypatch):
        """При туннеле sslmode доезжает до libpq (проверка имени хоста — на 127.0.0.1)."""
        captured = _install(monkeypatch)
        plugin = mod.PostgresPlugin()

        await plugin.initialize(
            {
                "host": "db.internal",
                "ssl_mode": "verify-ca",
                "ssh": {"host": "bastion", "tunnel": True},
            }
        )

        assert captured["sslmode"] == "verify-ca"
