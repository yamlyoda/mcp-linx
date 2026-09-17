"""B7: SSH host-key policy — дефолт `RejectPolicy` (anti-MITM) + opt-in ослабления."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import paramiko
import pytest


class _FakeSSHClient:
    """Подмена `paramiko.SSHClient`: без сети, с записью policy и connect-параметров."""

    def __init__(self) -> None:
        self.policy: Any = None
        self.connect_kwargs: dict[str, Any] | None = None
        self.closed = False
        self.host_keys: list[Any] = []
        self.transport = MagicMock()
        self.transport.is_active.return_value = True
        self.exec_command = MagicMock()
        stdout, stderr = MagicMock(), MagicMock()
        stdout.read.return_value = b"OK\n"
        stdout.channel.recv_exit_status.return_value = 0
        stderr.read.return_value = b""
        self.exec_command.return_value = (MagicMock(), stdout, stderr)

    def get_transport(self):
        return self.transport

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
            "timeout": 10,
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
            "timeout": 10,
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


@pytest.mark.asyncio
async def test_pool_reuse_keepalive_and_reconnect(ssh_mod):
    mod, created = ssh_mod
    adapter = mod.SSHAdapter({"host": "example.com"})
    assert adapter.client is None
    await adapter.connect()
    await adapter.connect()
    assert len(created) == 1
    assert adapter.client is created[0]
    created[0].transport.set_keepalive.assert_called_once_with(30)
    created[0].transport.is_active.return_value = False
    result = await adapter.execute_command("echo OK", timeout=7)
    assert len(created) == 2
    assert created[0].closed
    assert adapter.client is created[1]
    created[1].exec_command.assert_called_once_with("echo OK", timeout=7)
    assert result == {"stdout": "OK\n", "stderr": "", "returncode": 0, "command": "echo OK"}
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_disconnect_isolated_and_reopen(ssh_mod):
    mod, created = ssh_mod
    first = mod.SSHAdapter({"host": "example.com"})
    second = mod.SSHAdapter({"host": "example.com"})
    await first.connect()
    await second.connect()
    await first.disconnect()
    await first.disconnect()
    assert created[0].closed
    assert not created[1].closed
    await first.connect()
    assert len(created) == 3
    assert first.client is created[2]
    await first.disconnect()
    await second.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("returncode, expected", [(0, True), (1, False)])
async def test_ping_uses_exit_status(ssh_mod, returncode, expected):
    mod, created = ssh_mod
    adapter = mod.SSHAdapter()
    await adapter.connect()
    created[0].exec_command.return_value[1].channel.recv_exit_status.return_value = returncode
    assert await adapter.ping() is expected
    created[0].exec_command.assert_called_once_with("echo OK", timeout=5)
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_connection_error_ping_and_execute(ssh_mod, monkeypatch):
    mod, _ = ssh_mod
    adapter = mod.SSHAdapter()
    monkeypatch.setattr(adapter._pool, "get", MagicMock(side_effect=OSError("unreachable")))
    assert await adapter.ping() is False
    with pytest.raises(OSError, match="unreachable"):
        await adapter.execute_command("echo OK")
    assert adapter.client is None


@pytest.mark.asyncio
async def test_execute_and_parse_and_command_error(ssh_mod):
    mod, created = ssh_mod
    adapter = mod.SSHAdapter()
    assert await adapter.execute_and_parse("echo OK", str.strip) == "OK"
    created[0].exec_command.assert_called_once_with("echo OK", timeout=30)
    _, stdout, stderr = created[0].exec_command.return_value
    stdout.read.return_value = b""
    stdout.channel.recv_exit_status.return_value = 1
    stderr.read.return_value = b"failed"
    with pytest.raises(RuntimeError, match="Command failed: failed"):
        await adapter.execute_and_parse("echo OK", str.strip)
    await adapter.disconnect()
