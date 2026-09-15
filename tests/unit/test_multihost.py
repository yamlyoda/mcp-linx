"""Тесты multi-host: HostRegistry, SSHConnectionPool, RemoteHostAdapter, _resolve_adapter."""

from unittest.mock import MagicMock, patch

import pytest

from mcp_linx.adapters.ssh_pool import RemoteHostAdapter, SSHConnectionPool
from mcp_linx.multihost import HostRegistry
from mcp_linx.plugins.linux import LinuxPlugin

HOSTS_CONFIG = {
    "web-1": {"host": "10.130.0.23", "username": "user", "key_file": "~/.ssh/id_rsa"},
    "db-1": {"host": "10.130.0.24", "username": "user", "key_file": "~/.ssh/id_rsa"},
}


def _fake_client(alive: bool = True) -> MagicMock:
    client = MagicMock()
    transport = MagicMock()
    transport.is_active.return_value = alive
    client.get_transport.return_value = transport
    return client


def _fake_io(stdout: bytes = b"OK\n", rc: int = 0) -> tuple[MagicMock, MagicMock, MagicMock]:
    out = MagicMock()
    out.channel.recv_exit_status.return_value = rc
    out.read.return_value = stdout
    err = MagicMock()
    err.read.return_value = b""
    return MagicMock(), out, err


# ---------- HostRegistry ----------


class TestHostRegistry:
    def test_empty_config(self) -> None:
        reg = HostRegistry({})
        assert reg.list_hosts() == []
        assert not reg.has_host("web-1")

    def test_lists_hosts(self) -> None:
        reg = HostRegistry({"hosts": HOSTS_CONFIG})
        assert reg.list_hosts() == ["db-1", "web-1"]
        assert reg.has_host("web-1")

    def test_unknown_host_raises_with_available(self) -> None:
        reg = HostRegistry({"hosts": HOSTS_CONFIG})
        with pytest.raises(KeyError, match="Unknown host 'nope'.*db-1.*web-1"):
            reg.get_adapter("nope")

    def test_adapter_cached(self) -> None:
        reg = HostRegistry({"hosts": HOSTS_CONFIG})
        a1 = reg.get_adapter("web-1")
        a2 = reg.get_adapter("web-1")
        assert a1 is a2
        assert isinstance(a1, RemoteHostAdapter)
        assert a1.config == HOSTS_CONFIG["web-1"]


# ---------- SSHConnectionPool ----------


class TestSSHConnectionPool:
    def test_reuses_live_client(self) -> None:
        pool = SSHConnectionPool()
        fake = _fake_client(alive=True)
        with patch("mcp_linx.adapters.ssh_pool.paramiko.SSHClient", return_value=fake):
            c1 = pool.get(HOSTS_CONFIG["web-1"])
            c2 = pool.get(HOSTS_CONFIG["web-1"])
        assert c1 is fake and c2 is fake

    def test_reconnects_dead_client(self) -> None:
        pool = SSHConnectionPool()
        dead = _fake_client(alive=False)
        fresh = _fake_client(alive=True)
        with patch("mcp_linx.adapters.ssh_pool.paramiko.SSHClient", side_effect=[dead, fresh]):
            assert pool.get(HOSTS_CONFIG["web-1"]) is dead
            assert pool.get(HOSTS_CONFIG["web-1"]) is fresh

    def test_different_hosts_different_clients(self) -> None:
        pool = SSHConnectionPool()
        clients = [_fake_client(), _fake_client()]
        with patch("mcp_linx.adapters.ssh_pool.paramiko.SSHClient", side_effect=clients):
            assert pool.get(HOSTS_CONFIG["web-1"]) is clients[0]
            assert pool.get(HOSTS_CONFIG["db-1"]) is clients[1]

    def test_close_all(self) -> None:
        pool = SSHConnectionPool()
        fake = _fake_client()
        with patch("mcp_linx.adapters.ssh_pool.paramiko.SSHClient", return_value=fake):
            pool.get(HOSTS_CONFIG["web-1"])
        pool.close_all()
        fake.close.assert_called_once()
        assert pool._clients == {}

    def test_keyfile_priority_over_password(self) -> None:
        """key_file имеет приоритет над password."""
        pool = SSHConnectionPool()
        fake = _fake_client()
        cfg = {**HOSTS_CONFIG["web-1"], "password": "secret"}
        with patch("mcp_linx.adapters.ssh_pool.paramiko.SSHClient", return_value=fake) as cls:
            pool.get(cfg)
        kwargs = cls.return_value.connect.call_args.kwargs
        assert kwargs["key_filename"] == "~/.ssh/id_rsa"
        assert "password" not in kwargs


# ---------- RemoteHostAdapter ----------


class TestRemoteHostAdapter:
    def _adapter(self) -> tuple[RemoteHostAdapter, MagicMock]:
        fake = _fake_client()
        pool = MagicMock()
        pool.get.return_value = fake
        adapter = RemoteHostAdapter(pool, HOSTS_CONFIG["web-1"])
        return adapter, fake

    @pytest.mark.asyncio
    async def test_execute_command_parses_result(self) -> None:
        adapter, fake = self._adapter()
        fake.exec_command.return_value = _fake_io(b"Linux host\n", rc=0)
        result = await adapter.execute_command("uname -a")
        assert result["returncode"] == 0
        assert result["stdout"] == "Linux host\n"
        assert result["stderr"] == ""
        assert result["command"] == "uname -a"

    @pytest.mark.asyncio
    async def test_ping_ok(self) -> None:
        adapter, fake = self._adapter()
        fake.exec_command.return_value = _fake_io(b"OK\n", rc=0)
        assert await adapter.ping() is True

    @pytest.mark.asyncio
    async def test_ping_connection_error(self) -> None:
        pool = MagicMock()
        pool.get.side_effect = OSError("unreachable")
        adapter = RemoteHostAdapter(pool, HOSTS_CONFIG["web-1"])
        assert await adapter.ping() is False


# ---------- DiagnosticPlugin._resolve_adapter ----------


class TestResolveAdapter:
    def _plugin(self, hosts: HostRegistry | None) -> LinuxPlugin:
        plugin = LinuxPlugin()
        plugin.hosts = hosts
        plugin._adapter = MagicMock()
        return plugin

    @pytest.mark.asyncio
    async def test_none_host_returns_primary(self) -> None:
        reg = HostRegistry({"hosts": HOSTS_CONFIG})
        plugin = self._plugin(reg)
        assert plugin._resolve_adapter(None) is plugin._adapter

    @pytest.mark.asyncio
    async def test_host_returns_registry_adapter(self) -> None:
        reg = HostRegistry({"hosts": HOSTS_CONFIG})
        plugin = self._plugin(reg)
        adapter = plugin._resolve_adapter("web-1")
        assert isinstance(adapter, RemoteHostAdapter)
        assert adapter.config == HOSTS_CONFIG["web-1"]

    @pytest.mark.asyncio
    async def test_host_without_registry_raises(self) -> None:
        plugin = self._plugin(None)
        with pytest.raises(RuntimeError, match="Multi-host not configured.*'web-9'"):
            plugin._resolve_adapter("web-9")

    @pytest.mark.asyncio
    async def test_unknown_host_propagates(self) -> None:
        reg = HostRegistry({"hosts": HOSTS_CONFIG})
        plugin = self._plugin(reg)
        with pytest.raises(KeyError, match="Unknown host"):
            plugin._resolve_adapter("ghost")
