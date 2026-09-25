"""Unit tests для `plugins/netdiag/tools.py` (волна 14).

Без сети: `httpx.AsyncClient`, `socket`/`ssl` и `asyncio.open_connection`
подменяются фейками на уровне модуля. Покрываем HTTP-коды, TLS-сроки,
DNS-резолвинг и TCP-пробы.
"""

from __future__ import annotations

import socket as _real_socket
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_linx.plugins.netdiag import NetdiagPlugin
from mcp_linx.types import Status


def _plugin(**attrs: Any) -> MagicMock:
    plugin = MagicMock(spec=NetdiagPlugin)
    plugin._config = {}
    for name, value in attrs.items():
        setattr(plugin, name, value)
    return plugin


class _FakeResponse:
    def __init__(self, status_code: int = 200, url: str = "https://example.com"):
        self.status_code = status_code
        self.url = url
        self.headers = {"server": "nginx", "content-type": "text/html", "content-length": "12"}


def _install_http(monkeypatch, status_code: int = 200, exc: Exception | None = None) -> None:
    import mcp_linx.plugins.netdiag.tools as tools_mod

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *exc_info: object) -> bool:
            return False

        async def get(self, url: str, **kwargs: Any) -> _FakeResponse:
            if exc is not None:
                raise exc
            return _FakeResponse(status_code=status_code, url=url)

    monkeypatch.setattr(tools_mod.httpx, "AsyncClient", FakeClient)


class TestHttpCheck:
    @pytest.mark.asyncio
    async def test_ok(self, monkeypatch):
        from mcp_linx.plugins.netdiag.tools import http_check

        _install_http(monkeypatch, 200)
        result = await http_check(_plugin(), {"url": "https://example.com"})

        assert result.status == Status.HEALTHY
        assert result.data["status_code"] == 200
        assert result.data["server"] == "nginx"

    @pytest.mark.asyncio
    async def test_server_error_is_degraded(self, monkeypatch):
        from mcp_linx.plugins.netdiag.tools import http_check

        _install_http(monkeypatch, 502)
        result = await http_check(_plugin(), {"url": "https://example.com"})

        assert result.status == Status.DEGRADED
        assert any("502" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_client_error_is_degraded(self, monkeypatch):
        from mcp_linx.plugins.netdiag.tools import http_check

        _install_http(monkeypatch, 404)
        result = await http_check(_plugin(), {"url": "https://example.com"})

        assert result.status == Status.DEGRADED
        assert any("404" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_slow_response_is_degraded(self, monkeypatch):
        import mcp_linx.plugins.netdiag.tools as tools_mod
        from mcp_linx.plugins.netdiag.tools import http_check

        _install_http(monkeypatch, 200)
        # Патчим имя `time` только в неймспейсе модуля, не трогая event loop:
        # первый вызов (старт) = 0.0, все последующие = 4.0 → 4000 мс.
        ticks = iter([0.0, *([4.0] * 1000)])
        monkeypatch.setattr(tools_mod, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
        result = await http_check(_plugin(), {"url": "https://example.com"})

        assert result.status == Status.DEGRADED
        assert result.data["elapsed_ms"] == 4000.0

    @pytest.mark.asyncio
    async def test_connection_error(self, monkeypatch):
        from mcp_linx.plugins.netdiag.tools import http_check

        _install_http(monkeypatch, exc=ConnectionError("refused"))
        result = await http_check(_plugin(), {"url": "https://example.com"})

        assert result.status == Status.ERROR
        assert "refused" in (result.error_message or "")


class _FakeSock:
    def __enter__(self) -> _FakeSock:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeSSLSock(_FakeSock):
    def __init__(self, cert: dict[str, Any], chain_len: int = 2):
        self._cert = cert
        self._chain = [object()] * chain_len

    def getpeercert(self) -> dict[str, Any]:
        return self._cert

    def getpeercertchain(self) -> list[Any]:
        return self._chain


def _cert(not_after: str) -> dict[str, Any]:
    return {
        "notAfter": not_after,
        "issuer": ((("CN", "Test CA"),),),
        "subject": ((("CN", "example.com"),),),
        "subjectAltName": (("DNS", "example.com"),),
    }


def _install_tls(monkeypatch, cert: dict[str, Any] | None, exc: Exception | None = None) -> None:
    import mcp_linx.plugins.netdiag.tools as tools_mod

    def _connect(*args: Any, **kwargs: Any) -> _FakeSock:
        if exc is not None:
            raise exc
        return _FakeSock()

    def _wrap(sock: Any, server_hostname: str | None = None) -> _FakeSSLSock:
        assert cert is not None
        return _FakeSSLSock(cert)

    fake_socket = SimpleNamespace(create_connection=_connect)
    fake_ssl = SimpleNamespace(create_default_context=lambda: SimpleNamespace(wrap_socket=_wrap))
    monkeypatch.setattr(tools_mod, "socket", fake_socket)
    monkeypatch.setattr(tools_mod, "ssl", fake_ssl)


class TestTlsCheck:
    @pytest.mark.asyncio
    async def test_valid_cert(self, monkeypatch):
        from mcp_linx.plugins.netdiag.tools import tls_check

        not_after = (datetime.now(UTC) + timedelta(days=90)).strftime("%b %d %H:%M:%S %Y GMT")
        _install_tls(monkeypatch, _cert(not_after))
        result = await tls_check(_plugin(), {"host": "example.com"})

        assert result.status == Status.HEALTHY
        assert result.data["days_left"] >= 89
        assert result.data["san"] == ["example.com"]
        assert result.data["chain_length"] == 2

    @pytest.mark.asyncio
    async def test_expiring_soon_is_degraded(self, monkeypatch):
        from mcp_linx.plugins.netdiag.tools import tls_check

        not_after = (datetime.now(UTC) + timedelta(days=7)).strftime("%b %d %H:%M:%S %Y GMT")
        _install_tls(monkeypatch, _cert(not_after))
        result = await tls_check(_plugin(), {"host": "example.com"})

        assert result.status == Status.DEGRADED
        assert any("истекает" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_expired_is_critical(self, monkeypatch):
        from mcp_linx.plugins.netdiag.tools import tls_check

        not_after = (datetime.now(UTC) - timedelta(days=1)).strftime("%b %d %H:%M:%S %Y GMT")
        _install_tls(monkeypatch, _cert(not_after))
        result = await tls_check(_plugin(), {"host": "example.com"})

        assert result.status == Status.CRITICAL

    @pytest.mark.asyncio
    async def test_connection_error(self, monkeypatch):
        from mcp_linx.plugins.netdiag.tools import tls_check

        _install_tls(monkeypatch, None, exc=TimeoutError("timed out"))
        result = await tls_check(_plugin(), {"host": "example.com"})

        assert result.status == Status.ERROR


def _install_dns(monkeypatch, infos: list[Any] | None = None, exc: Exception | None = None) -> None:
    import mcp_linx.plugins.netdiag.tools as tools_mod

    def _getaddrinfo(name: str, port: Any) -> list[Any]:
        if exc is not None:
            raise exc
        return infos or []

    fake_socket = SimpleNamespace(
        getaddrinfo=_getaddrinfo,
        AF_INET=_real_socket.AF_INET,
        AF_INET6=_real_socket.AF_INET6,
    )
    monkeypatch.setattr(tools_mod, "socket", fake_socket)


class TestDnsResolve:
    @pytest.mark.asyncio
    async def test_resolves_v4_and_v6(self, monkeypatch):
        from mcp_linx.plugins.netdiag.tools import dns_resolve

        infos = [
            (_real_socket.AF_INET, 0, 0, "", ("93.184.216.34", 0)),
            (_real_socket.AF_INET, 0, 0, "", ("93.184.216.34", 0)),
            (_real_socket.AF_INET6, 0, 0, "", ("2606:2800:220:1:248:1893:25c8:1946", 0, 0, 0)),
        ]
        _install_dns(monkeypatch, infos)
        result = await dns_resolve(_plugin(), {"name": "example.com"})

        assert result.status == Status.HEALTHY
        assert result.data["a"] == ["93.184.216.34"]
        assert len(result.data["aaaa"]) == 1

    @pytest.mark.asyncio
    async def test_no_records_is_degraded(self, monkeypatch):
        from mcp_linx.plugins.netdiag.tools import dns_resolve

        _install_dns(monkeypatch, [])
        result = await dns_resolve(_plugin(), {"name": "empty.example.com"})

        assert result.status == Status.DEGRADED

    @pytest.mark.asyncio
    async def test_gaierror(self, monkeypatch):
        from mcp_linx.plugins.netdiag.tools import dns_resolve

        _install_dns(monkeypatch, exc=_real_socket.gaierror("NXDOMAIN"))
        result = await dns_resolve(_plugin(), {"name": "bad.invalid"})

        assert result.status == Status.ERROR
        assert "bad.invalid" in (result.error_message or "")


class _FakeWriter:
    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


class TestTcpConnect:
    @pytest.mark.asyncio
    async def test_reachable(self, monkeypatch):
        import mcp_linx.plugins.netdiag.tools as tools_mod
        from mcp_linx.plugins.netdiag.tools import tcp_connect

        async def _open(host: str, port: int):
            return MagicMock(), _FakeWriter()

        monkeypatch.setattr(tools_mod.asyncio, "open_connection", _open)
        result = await tcp_connect(_plugin(), {"host": "127.0.0.1", "port": 80})

        assert result.status == Status.HEALTHY
        assert result.data["reachable"] is True

    @pytest.mark.asyncio
    async def test_refused_is_unhealthy(self, monkeypatch):
        import mcp_linx.plugins.netdiag.tools as tools_mod
        from mcp_linx.plugins.netdiag.tools import tcp_connect

        async def _open(host: str, port: int):
            raise ConnectionRefusedError("refused")

        monkeypatch.setattr(tools_mod.asyncio, "open_connection", _open)
        result = await tcp_connect(_plugin(), {"host": "127.0.0.1", "port": 1})

        assert result.status == Status.UNHEALTHY
        assert result.data["reachable"] is False


class TestPrivilegedProbes:
    @pytest.mark.asyncio
    async def test_tcp_connect_as_failure_is_unhealthy(self):
        from mcp_linx.plugins.netdiag.tools import tcp_connect_as

        plugin = _plugin(
            _config={"privileged_tools": True},
            _run_privileged=AsyncMock(
                return_value={"stdout": "", "stderr": "timeout", "returncode": 124}
            ),
        )
        result = await tcp_connect_as(
            plugin, {"host": "10.0.0.1", "port": 5432, "user": "www-data"}
        )

        assert result.status == Status.UNHEALTHY
        assert any("per-uid" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_tcpdump_probe_with_packets(self):
        from mcp_linx.plugins.netdiag.tools import tcpdump_probe

        plugin = _plugin(
            _config={"privileged_tools": True},
            _run_privileged=AsyncMock(
                return_value={
                    "stdout": "12:00:01.000 IP 10.0.0.1 > 10.0.0.2: SYN\n"
                    "12:00:01.100 IP 10.0.0.2 > 10.0.0.1: SYN-ACK\n",
                    "stderr": "",
                    "returncode": 0,
                }
            ),
        )
        result = await tcpdump_probe(plugin, {"host": "10.0.0.2", "port": 5432})

        assert result.status == Status.HEALTHY
        assert result.data["packets_seen"] == 2
