"""B7: SSH host-key policy — дефолт `RejectPolicy` (anti-MITM) + opt-in ослабления."""

from __future__ import annotations

from typing import Any

import paramiko
import pytest


class _FakeSSHClient:
    """Подмена `paramiko.SSHClient`: без сети, с записью policy и connect-параметров."""

    def __init__(self) -> None:
        self.policy: Any = None
        self.connect_kwargs: dict[str, Any] | None = None
        self.closed = False
        self.host_keys: list[Any] = []

    def set_missing_host_key_policy(self, policy: Any) -> None:
        self.policy = policy

    def load_host_keys(self, path: str) -> None:
        self.host_keys.append(path)

    def load_system_host_keys(self) -> None:
        self.host_keys.append(None)

    def connect(self, **kwargs: Any) -> None:
        self.connect_kwargs = kwargs

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def ssh_mod(monkeypatch):
    """Модуль адаптера с подменённым `paramiko.SSHClient` и списком созданных клиентов."""
    import mcp_linx.adapters.ssh as mod

    created: list[_FakeSSHClient] = []

    def factory() -> _FakeSSHClient:
        client = _FakeSSHClient()
        created.append(client)
        return client

    monkeypatch.setattr(mod.paramiko, "SSHClient", factory)
    return mod, created


class TestHostKeyPolicy:
    @pytest.mark.asyncio
    async def test_default_is_reject(self, ssh_mod):
        """Без `host_key_policy` в конфиге — строгий `RejectPolicy` (anti-MITM)."""
        mod, created = ssh_mod
        adapter = mod.SSHAdapter({"host": "example.com"})

        await adapter.connect()

        assert isinstance(created[0].policy, paramiko.RejectPolicy)

    @pytest.mark.parametrize(
        ("configured", "expected"),
        [
            ("auto_add", paramiko.AutoAddPolicy),
            ("AUTO_ADD", paramiko.AutoAddPolicy),
            ("warning", paramiko.WarningPolicy),
            ("WARNING", paramiko.WarningPolicy),
            ("reject", paramiko.RejectPolicy),
            ("", paramiko.RejectPolicy),
            ("nonsense", paramiko.RejectPolicy),  # неизвестное значение → fail-safe
        ],
    )
    @pytest.mark.asyncio
    async def test_policy_mapping(self, ssh_mod, configured, expected):
        mod, created = ssh_mod
        adapter = mod.SSHAdapter({"host": "example.com", "host_key_policy": configured})

        await adapter.connect()

        assert isinstance(created[0].policy, expected)


class TestConnectParams:
    @pytest.mark.asyncio
    async def test_key_file_wins_over_password(self, ssh_mod):
        mod, created = ssh_mod
        adapter = mod.SSHAdapter(
            {
                "host": "10.0.0.1",
                "port": 2222,
                "username": "user",
                "key_file": "~/.ssh/id_rsa",
                "password": "secret",
            }
        )

        await adapter.connect()

        kwargs = created[0].connect_kwargs
        assert kwargs == {
            "hostname": "10.0.0.1",
            "port": 2222,
            "username": "user",
            "key_filename": "~/.ssh/id_rsa",
        }
        assert "password" not in kwargs

    @pytest.mark.asyncio
    async def test_password_used_without_key_file(self, ssh_mod):
        mod, created = ssh_mod
        adapter = mod.SSHAdapter({"host": "10.0.0.2", "password": "secret"})

        await adapter.connect()

        assert created[0].connect_kwargs == {
            "hostname": "10.0.0.2",
            "port": 22,
            "password": "secret",
        }

    @pytest.mark.asyncio
    async def test_known_hosts_from_config(self, ssh_mod):
        mod, created = ssh_mod
        adapter = mod.SSHAdapter({"host": "10.0.0.3", "known_hosts": "/etc/ssh/known_hosts"})

        await adapter.connect()

        assert created[0].host_keys == ["/etc/ssh/known_hosts"]

    @pytest.mark.asyncio
    async def test_system_host_keys_when_known_hosts_absent(self, ssh_mod):
        mod, created = ssh_mod
        adapter = mod.SSHAdapter({"host": "10.0.0.4"})

        await adapter.connect()

        assert created[0].host_keys == [None]

    @pytest.mark.asyncio
    async def test_disconnect_closes_client(self, ssh_mod):
        mod, created = ssh_mod
        adapter = mod.SSHAdapter({"host": "10.0.0.5"})
        await adapter.connect()

        await adapter.disconnect()

        assert created[0].closed is True
        assert adapter._client is None
