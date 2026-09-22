"""Wave 10 (E2): `SSHTunnel` — локальный форвард через `direct-tcpip`.

Фейковый SSH-транспорт + канал на socketpair: проверяем реальную перекачку байт
в обе стороны, параметры `open_channel`, остановку и ветки ошибок. Сети нет.
"""

from __future__ import annotations

import socket
import time
from contextlib import suppress
from typing import Any

import pytest

from mcp_linx.adapters.ssh_pool import SSHTunnel


class _FakeChannel:
    """Канал paramiko: recv/sendall/shutdown/close поверх socketpair."""

    def __init__(self) -> None:
        self._channel, self._peer = socket.socketpair()

    def recv(self, size: int) -> bytes:
        return self._channel.recv(size)

    def sendall(self, data: bytes) -> None:
        self._channel.sendall(data)

    def shutdown(self, how: int) -> None:
        with suppress(Exception):
            self._channel.shutdown(how)

    def close(self) -> None:
        for sock in (self._channel, self._peer):
            with suppress(Exception):
                sock.close()

    # --- сторона «удалённого сервиса» (для теста) ---
    def read(self, size: int) -> bytes:
        return self._peer.recv(size)

    def feed(self, data: bytes) -> None:
        self._peer.sendall(data)


class _FakeTransport:
    def __init__(self, channel: _FakeChannel | None = None, error: Exception | None = None):
        self.channel = channel
        self.error = error
        self.opened: list[tuple[str, tuple[str, int], Any]] = []

    def open_channel(self, kind: str, dest: tuple[str, int], src: Any) -> _FakeChannel:
        self.opened.append((kind, dest, src))
        if self.error is not None:
            raise self.error
        assert self.channel is not None
        return self.channel


class _FakeClient:
    def __init__(self, transport: _FakeTransport | None) -> None:
        self._transport = transport

    def get_transport(self) -> _FakeTransport | None:
        return self._transport


def _read_n(read: Any, size: int, timeout: float = 3.0) -> bytes:
    """Прочитать ровно `size` байт через `read(size)` (или упасть по таймауту)."""
    deadline = time.monotonic() + timeout
    data = b""
    while len(data) < size and time.monotonic() < deadline:
        try:
            chunk = read(size - len(data))
        except TimeoutError:
            break
        if not chunk:
            break
        data += chunk
    return data


class TestTunnelLifecycle:
    def test_local_address_before_start_raises(self):
        tunnel = SSHTunnel(_FakeClient(_FakeTransport(_FakeChannel())), "db", 5432)
        with pytest.raises(RuntimeError, match="not started"):
            _ = tunnel.local_address

    def test_start_without_transport_raises(self):
        tunnel = SSHTunnel(_FakeClient(None), "db", 5432)
        with pytest.raises(RuntimeError, match="transport is not available"):
            tunnel.start()

    def test_stop_is_idempotent(self):
        channel = _FakeChannel()
        tunnel = SSHTunnel(_FakeClient(_FakeTransport(channel)), "db", 5432)
        tunnel.start()

        tunnel.stop()
        tunnel.stop()  # повторный вызов не должен падать

        with pytest.raises(RuntimeError, match="not started"):
            _ = tunnel.local_address


class TestTunnelForwarding:
    def test_bytes_flow_both_directions(self):
        channel = _FakeChannel()
        transport = _FakeTransport(channel)
        tunnel = SSHTunnel(_FakeClient(transport), "db.internal", 5432)
        tunnel.start()
        host, port = tunnel.local_address

        try:
            client = socket.create_connection((host, port), timeout=3)
            try:
                client.settimeout(3)
                client.sendall(b"SELECT 1")

                assert _read_n(channel.read, 8) == b"SELECT 1"
                assert transport.opened == [
                    ("direct-tcpip", ("db.internal", 5432), client.getsockname())
                ]

                channel.feed(b"row")
                assert _read_n(client.recv, 3) == b"row"
            finally:
                with suppress(Exception):
                    client.close()
        finally:
            tunnel.stop()

    def test_channel_open_failure_closes_client_connection(self):
        transport = _FakeTransport(error=RuntimeError("channel denied"))
        tunnel = SSHTunnel(_FakeClient(transport), "db", 5432)
        tunnel.start()
        host, port = tunnel.local_address

        try:
            client = socket.create_connection((host, port), timeout=3)
            client.settimeout(3)
            # обработчик закрывает соединение, не роняя сервер
            assert client.recv(1) == b""
            # listener продолжает принимать новые соединения
            again = socket.create_connection((host, port), timeout=3)
            again.close()
            client.close()
        finally:
            tunnel.stop()

    def test_explicit_local_port_is_used(self):
        channel = _FakeChannel()
        tunnel = SSHTunnel(_FakeClient(_FakeTransport(channel)), "db", 5432, local_port=0)
        tunnel.start()
        try:
            host, port = tunnel.local_address
            assert host == "127.0.0.1"
            assert port > 0
        finally:
            tunnel.stop()

    def test_accepts_multiple_connections(self):
        channel = _FakeChannel()
        transport = _FakeTransport(channel)
        tunnel = SSHTunnel(_FakeClient(transport), "db", 5432)
        tunnel.start()
        host, port = tunnel.local_address

        try:
            socks = [socket.create_connection((host, port), timeout=3) for _ in range(3)]
            for sock in socks:
                sock.close()
            time.sleep(0.2)
            assert len(transport.opened) == 3
        finally:
            tunnel.stop()
