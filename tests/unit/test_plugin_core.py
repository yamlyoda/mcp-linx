"""B2: ядро плагинов postgres / kubernetes / prometheus / loki / redis.

Без сети и без реальных сервисов: psycopg2, httpx и адаптеры подменяются фейками.
Покрываем `initialize` (маппинг конфига), `health_check` (healthy/unhealthy/error),
построение команд/URL, `_execute_query*` и `destroy`.
"""

from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import AsyncMock

import pytest


class _RecordingAdapter:
    """Адаптер-заглушка: пишет вызовы, отдаёт заранее заданные результаты."""

    def __init__(self, result: dict[str, Any] | None = None, exc: Exception | None = None):
        self.calls: list[tuple[str, int | None]] = []
        self._result = (
            result if result is not None else {"stdout": "", "stderr": "", "returncode": 0}
        )
        self._exc = exc

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def execute_command(self, command: str, timeout: int | None = None) -> dict[str, Any]:
        self.calls.append((command, timeout))
        if self._exc is not None:
            raise self._exc
        return dict(self._result)


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]] | None = None, description: Any = None):
        self._rows = rows or []
        self.description = description
        self.queries: list[tuple[str, Any]] = []

    def execute(self, query: str, params: Any = None) -> None:
        self.queries.append((query, params))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeConn:
    def __init__(self, cursor: _FakeCursor):
        self._cursor = cursor
        self.autocommit: bool | None = None
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def pg(monkeypatch):
    """Плагин postgres + запись `psycopg2.connect(**kwargs)` и подставленный cursor."""
    import mcp_linx.plugins.postgres as mod

    state: dict[str, Any] = {"calls": [], "conn": None}

    def _install(cursor: _FakeCursor) -> _FakeCursor:
        def fake_connect(**kwargs: Any) -> _FakeConn:
            state["calls"].append(kwargs)
            conn = _FakeConn(cursor)
            state["conn"] = conn
            return conn

        monkeypatch.setattr(mod.psycopg2, "connect", fake_connect)
        return cursor

    return mod, state, _install


@pytest.fixture()
def http(monkeypatch):
    """Установить фейковый `httpx.AsyncClient` в модуле плагина; вернуть (модуль, seen)."""

    def _install(module: str, status_code: int = 200, exc: Exception | None = None):
        mod = importlib.import_module(module)
        seen: dict[str, Any] = {}

        class FakeResponse:
            def __init__(self) -> None:
                self.status_code = status_code

            def json(self) -> Any:
                return seen.get("payload")

            def raise_for_status(self) -> None:
                if self.status_code >= 400:
                    raise RuntimeError(f"HTTP {self.status_code}")

        class FakeClient:
            def __init__(self, timeout: Any = None, **kwargs: Any) -> None:
                seen["timeout"] = timeout

            async def __aenter__(self) -> FakeClient:
                return self

            async def __aexit__(self, *exc: object) -> bool:
                return False

            async def _request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
                seen.setdefault("requests", []).append((method, url, kwargs))
                if exc is not None:
                    raise exc
                return FakeResponse()

            async def get(self, url: str, **kwargs: Any) -> FakeResponse:
                return await self._request("GET", url, **kwargs)

            async def post(self, url: str, **kwargs: Any) -> FakeResponse:
                return await self._request("POST", url, **kwargs)

        monkeypatch.setattr(mod.httpx, "AsyncClient", FakeClient)
        return mod, seen

    return _install


class TestPostgresPlugin:
    @pytest.mark.asyncio
    async def test_initialize_maps_config_to_connect_kwargs(self, pg):
        mod, state, install = pg
        install(_FakeCursor(rows=[(1,)], description=[("?column?",)]))

        plugin = mod.PostgresPlugin()
        await plugin.initialize(
            {
                "host": "db.internal",
                "port": 6432,
                "database": "app",
                "user": "reader",
                "password": "s3cret",
                "ssl_mode": "verify-full",
            }
        )

        assert state["calls"] == [
            {
                "host": "db.internal",
                "port": 6432,
                "database": "app",
                "user": "reader",
                "password": "s3cret",
                "sslmode": "verify-full",
            }
        ]
        assert state["conn"].autocommit is True

    @pytest.mark.asyncio
    async def test_initialize_defaults_and_omits_empty_password(self, pg):
        mod, state, install = pg
        install(_FakeCursor())

        await mod.PostgresPlugin().initialize({})

        assert state["calls"] == [
            {
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "sslmode": "prefer",
            }
        ]

    @pytest.mark.asyncio
    async def test_initialize_omits_sslmode_when_blank(self, pg):
        mod, state, install = pg
        install(_FakeCursor())

        await mod.PostgresPlugin().initialize({"ssl_mode": ""})

        assert "sslmode" not in state["calls"][0]

    @pytest.mark.asyncio
    async def test_health_check_healthy_and_unhealthy(self, pg):
        mod, _, install = pg
        install(_FakeCursor(rows=[(1,)]))
        plugin = mod.PostgresPlugin()

        healthy = await plugin.health_check()

        assert healthy.status.value == "healthy"

        cursor = _FakeCursor(rows=[(0,)])
        install(cursor)
        plugin._conn = _FakeConn(cursor)

        unhealthy = await plugin.health_check()

        assert unhealthy.status.value == "unhealthy"

    @pytest.mark.asyncio
    async def test_health_check_error_when_connection_fails(self, pg):
        mod, state, install = pg

        class _BrokenCursor(_FakeCursor):
            def execute(self, query: str, params: Any = None) -> None:
                raise RuntimeError("connection reset")

        install(_BrokenCursor())

        health = await mod.PostgresPlugin().health_check()

        assert health.status.value == "error"
        assert "connection reset" in health.message

    @pytest.mark.asyncio
    async def test_execute_query_maps_rows_to_dicts(self, pg):
        mod, _, install = pg
        install(_FakeCursor(rows=[(1, "a"), (2, "b")], description=[("id",), ("name",)]))
        plugin = mod.PostgresPlugin()

        rows = await plugin._execute_query("SELECT id, name FROM t")

        assert rows == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]

    @pytest.mark.asyncio
    async def test_execute_query_without_description_is_empty(self, pg):
        mod, _, install = pg
        install(_FakeCursor(rows=[(1,)], description=None))

        assert await mod.PostgresPlugin()._execute_query("SET x = 1") == []

    @pytest.mark.asyncio
    async def test_execute_query_one_returns_first_or_none(self, pg):
        mod, _, install = pg
        install(_FakeCursor(rows=[("only",)], description=[("v",)]))
        plugin = mod.PostgresPlugin()

        assert await plugin._execute_query_one("SELECT v") == {"v": "only"}

        install(_FakeCursor(rows=[], description=[("v",)]))
        plugin._conn = None
        assert await plugin._execute_query_one("SELECT v") is None

    @pytest.mark.asyncio
    async def test_destroy_closes_connection(self, pg):
        mod, state, install = pg
        install(_FakeCursor())
        plugin = mod.PostgresPlugin()
        await plugin.initialize({})

        await plugin.destroy()

        assert state["conn"].closed is True
        assert plugin._conn is None


@pytest.mark.parametrize(
    ("name", "class_name", "endpoint"),
    [("prometheus", "PrometheusPlugin", "/-/healthy"), ("loki", "LokiPlugin", "/ready")],
)
@pytest.mark.parametrize(
    ("code", "exc", "expected"),
    [(200, None, "healthy"), (503, None, "unhealthy"), (200, RuntimeError("offline"), "error")],
)
async def test_http_plugin_health_and_config(http, name, class_name, endpoint, code, exc, expected):
    mod, seen = http(f"mcp_linx.plugins.{name}", status_code=code, exc=exc)
    plugin = getattr(mod, class_name)()
    assert plugin._headers() == {}
    await plugin.initialize(
        {"base_url": "http://metrics.test/", "timeout_seconds": 42, "token": "test-token"}
    )
    assert plugin._timeout == 42
    assert plugin._headers() == {"Authorization": "Bearer test-token"}

    health = await plugin.health_check()

    assert health.status.value == expected
    assert seen["timeout"] == 10
    assert seen["requests"] == [("GET", f"http://metrics.test{endpoint}", {})]
    if exc:
        assert "offline" in health.message
    await plugin.destroy()
    await plugin.initialize({"token": ""})
    assert plugin._headers() == {}
    assert plugin._timeout == 20


@pytest.mark.parametrize(
    ("name", "class_name"), [("kubernetes", "KubernetesPlugin"), ("redis", "RedisPlugin")]
)
@pytest.mark.parametrize("remote", [False, True])
async def test_shell_plugin_initialization_and_destroy(monkeypatch, name, class_name, remote):
    mod = importlib.import_module(f"mcp_linx.plugins.{name}")
    adapter = _RecordingAdapter()
    adapter.connect = AsyncMock()
    adapter.disconnect = AsyncMock()
    seen = []

    def factory(config):
        seen.append(config)
        return adapter

    monkeypatch.setattr(mod, "SSHAdapter" if remote else "LocalAdapter", factory)
    config = {"security": {"command_timeout_seconds": 42}}
    if remote:
        config["ssh"] = {"host": "test.invalid"}
    plugin = getattr(mod, class_name)()
    await plugin.initialize(config)
    assert seen == [config["ssh"] if remote else {}]
    assert plugin.command_timeout == 42
    adapter.connect.assert_awaited_once()
    await plugin.destroy()
    adapter.disconnect.assert_awaited_once()


@pytest.mark.parametrize(
    ("name", "class_name", "method", "args"),
    [
        ("kubernetes", "KubernetesPlugin", "_run", "kubectl get pods"),
        ("redis", "RedisPlugin", "_run_redis_cli", "PING"),
    ],
)
async def test_shell_plugin_adapter_error(name, class_name, method, args):
    from mcp_linx.security import SecurityGuard

    plugin = getattr(importlib.import_module(f"mcp_linx.plugins.{name}"), class_name)()
    with pytest.raises(RuntimeError, match="Plugin not initialized"):
        await getattr(plugin, method)(args)
    plugin._adapter = _RecordingAdapter(exc=RuntimeError("offline"))
    plugin._security = SecurityGuard({})
    result = await getattr(plugin, method)(args)
    assert result["returncode"] == 1
    assert result["stderr"] == "offline"
    assert result["stdout"] == ""


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ([{"returncode": 0, "stdout": '{"clientVersion":{"gitVersion":"v1.30"}}'}], "healthy"),
        ([{"returncode": 1}, {"returncode": 0}], "healthy"),
        ([{"returncode": 1}, {"returncode": 1}], "degraded"),
        ([RuntimeError("offline")], "error"),
    ],
)
async def test_kubernetes_health(results, expected):
    from mcp_linx.plugins.kubernetes import KubernetesPlugin

    plugin = KubernetesPlugin()
    plugin._run = AsyncMock(side_effect=results)
    health = await plugin.health_check()
    assert health.status.value == expected
    assert plugin._run.await_count == len(results)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"returncode": 0, "stdout": "PONG", "stderr": ""}, "healthy"),
        ({"returncode": 1, "stdout": "", "stderr": "offline"}, "unhealthy"),
        (RuntimeError("offline"), "error"),
    ],
)
async def test_redis_health(result, expected):
    from mcp_linx.plugins.redis import RedisPlugin

    plugin = RedisPlugin()
    plugin._run_redis_cli = AsyncMock(side_effect=[result])
    health = await plugin.health_check()
    assert health.status.value == expected
    plugin._run_redis_cli.assert_awaited_once_with("PING", timeout=10)


def test_shell_argument_builders():
    import shlex

    from mcp_linx.plugins.kubernetes import KubernetesPlugin
    from mcp_linx.plugins.redis import RedisPlugin

    kubernetes = KubernetesPlugin()
    kubernetes._kubeconfig = "/tmp/test config"
    kubernetes._context = "test context"
    assert shlex.split(kubernetes._kubectl_base()) == [
        "kubectl",
        "--kubeconfig",
        "/tmp/test config",
        "--context",
        "test context",
    ]
    redis = RedisPlugin()
    redis._host = "redis.test"
    redis._port = 6380
    redis._password = "test password"
    assert shlex.split(redis._base_args()) == [
        "redis-cli",
        "-h",
        "redis.test",
        "-p",
        "6380",
        "-a",
        "test password",
    ]
