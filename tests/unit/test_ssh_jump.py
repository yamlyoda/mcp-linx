"""Wave 13 (E3): jump host / bastion — SSH через `direct-tcpip`.

Проверяем, что при `jump_host` создаются два клиента (бастион и цель), канал
бастиона передаётся в `connect(sock=...)`, а бастион закрывается вместе с целью.
Сети нет: `paramiko.SSHClient` подменяется.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

import mcp_linx.adapters.ssh_pool as sp
from mcp_linx.adapters.ssh_pool import SSHConnectionPool

TARGET: dict[str, Any] = {
    "host": "db.internal",
    "port": 5432,
    "username": "ops",
    "key_file": "~/.ssh/id_rsa",
    "jump_host": "bastion.example.com",
    "jump_port": 2222,
    "jump_username": "jumper",
    "jump_key_file": "~/.ssh/jump",
}


class _FakeTransport:
    def __init__(self) -> None:
        self.channels: list[tuple[str, tuple[str, int], tuple[str, int]]] = []
        self.opened: list[MagicMock] = []
        self.keepalive: int | None = None
        self.active = True

    def open_channel(self, kind: str, dest: tuple[str, int], src: tuple[str, int]) -> MagicMock:
        self.channels.append((kind, dest, src))
        channel = MagicMock()
        channel.kind = kind
        self.opened.append(channel)
        return channel

    def set_keepalive(self, seconds: int) -> None:
        self.keepalive = seconds

    def is_active(self) -> bool:
        return self.active


class _FakeClient:
    def __init__(self) -> None:
        self.policy: Any = None
        self.connect_kwargs: dict[str, Any] | None = None
        self.host_keys: list[Any] = []
        self.closed = False
        self.transport = _FakeTransport()

    def set_missing_host_key_policy(self, policy: Any) -> None:
        self.policy = policy

    def load_host_keys(self, path: str) -> None:
        self.host_keys.append(path)

    def load_system_host_keys(self) -> None:
        self.host_keys.append(None)

    def connect(self, **kwargs: Any) -> None:
        self.connect_kwargs = kwargs

    def get_transport(self) -> _FakeTransport:
        return self.transport

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def clients(monkeypatch):
    """Список созданных клиентов в порядке появления (бастион, затем цель)."""
    created: list[_FakeClient] = []

    def factory() -> _FakeClient:
        client = _FakeClient()
        created.append(client)
        return client

    monkeypatch.setattr(sp.paramiko, "SSHClient", factory)
    return created


class TestDirectConnection:
    def test_no_jump_creates_single_client(self, clients):
        pool = SSHConnectionPool()

        pool.get({"host": "web-1", "port": 22})

        assert len(clients) == 1
        assert "sock" not in clients[0].connect_kwargs
        assert pool._jump_clients == {}


class TestJumpConnection:
    def test_creates_bastion_and_target_clients(self, clients):
        pool = SSHConnectionPool()

        pool.get(TARGET)

        assert len(clients) == 2
        bastion, target = clients

        assert bastion.connect_kwargs == {
            "hostname": "bastion.example.com",
            "port": 2222,
            "timeout": 10,
            "username": "jumper",
            "key_filename": "~/.ssh/jump",
        }
        assert target.connect_kwargs is not None
        assert target.connect_kwargs["hostname"] == "db.internal"
        assert target.connect_kwargs["port"] == 5432
        assert target.connect_kwargs["username"] == "ops"
        assert target.connect_kwargs["key_filename"] == "~/.ssh/id_rsa"
        assert "sock" in target.connect_kwargs

    def test_channel_targets_the_real_host_and_port(self, clients):
        pool = SSHConnectionPool()

        pool.get(TARGET)

        bastion, target = clients
        assert bastion.transport.channels == [
            ("direct-tcpip", ("db.internal", 5432), ("127.0.0.1", 0))
        ]
        # канал бастиона передан в connect целевого клиента как sock
        assert target.connect_kwargs["sock"] is bastion.transport.opened[0]

    def test_bastion_inherits_host_key_policy_and_known_hosts(self, clients):
        pool = SSHConnectionPool()

        pool.get({**TARGET, "host_key_policy": "auto_add", "known_hosts": "/etc/ssh/known"})

        bastion = clients[0]
        assert isinstance(bastion.policy, sp.paramiko.AutoAddPolicy)
        assert bastion.host_keys == ["/etc/ssh/known"]

    def test_jump_port_defaults_to_22(self, clients):
        config = {k: v for k, v in TARGET.items() if k != "jump_port"}
        pool = SSHConnectionPool()

        pool.get(config)

        assert clients[0].connect_kwargs["port"] == 22

    def test_missing_bastion_transport_raises(self, clients, monkeypatch):
        pool = SSHConnectionPool()
        monkeypatch.setattr(_FakeClient, "get_transport", lambda self: None)

        with pytest.raises(RuntimeError, match="Jump host transport is not available"):
            pool.get(TARGET)


class TestJumpCleanup:
    def test_drop_closes_bastion_too(self, clients):
        pool = SSHConnectionPool()
        pool.get(TARGET)
        bastion, target = clients

        pool.drop(TARGET)

        assert bastion.closed is True
        assert target.closed is True
        assert pool._clients == {} and pool._jump_clients == {}

    def test_close_all_closes_bastions(self, clients):
        pool = SSHConnectionPool()
        pool.get(TARGET)
        bastion, target = clients

        pool.close_all()

        assert bastion.closed is True
        assert target.closed is True
        assert pool._jump_clients == {}

    def test_reuses_same_target_client(self, clients):
        pool = SSHConnectionPool()

        first = pool.get(TARGET)
        second = pool.get(TARGET)

        assert first is second
        assert len(clients) == 2  # бастион и цель созданы один раз
