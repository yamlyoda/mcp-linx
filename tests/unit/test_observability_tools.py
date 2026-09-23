"""Wave 12 (B2): tools Prometheus и Loki — httpx-пути без сети.

`httpx.AsyncClient` подменяется: проверяем успешные ответы, HTTP-ошибки,
ошибки тела (`status != success`), degraded-ветки (firing/down) и валидацию
параметров. Плагины — минимальные заглушки с нужными атрибутами.
"""

from __future__ import annotations

from typing import Any

import pytest

import mcp_linx.plugins.loki.tools as loki_tools
import mcp_linx.plugins.prometheus.tools as prom_tools
from mcp_linx.types import Status


class _StubPlugin:
    """Заглушка плагина: только то, что читают tools."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url
        self._timeout = 5

    def _headers(self) -> dict[str, str]:
        return {"X-Scope-OrgID": "test"}


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or str(self._payload)

    def json(self) -> Any:
        return self._payload


class _FakeClient:
    """Асинхронный контекстный клиент: отдаёт заранее заданные ответы по порядку."""

    created: list[_FakeClient] = []

    def __init__(self, responses: list[_FakeResponse] | _FakeResponse, **kwargs: Any) -> None:
        self._responses = responses if isinstance(responses, list) else [responses]
        self.timeout = kwargs.get("timeout")
        self.requests: list[tuple[str, Any, Any]] = []
        type(self).created.append(self)

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def get(self, url: str, params: Any = None, headers: Any = None) -> _FakeResponse:
        self.requests.append((url, params, headers))
        if not self._responses:
            raise AssertionError("unexpected extra request")
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def _reset_clients():
    _FakeClient.created.clear()


def _install(module: Any, monkeypatch: Any, responses: Any) -> None:
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: _FakeClient(responses, **kw))


def _prom() -> _StubPlugin:
    return _StubPlugin("http://prometheus:9090")


def _loki() -> _StubPlugin:
    return _StubPlugin("http://loki:3100")


class TestPrometheusValidation:
    @pytest.mark.asyncio
    async def test_query_required(self):
        result = await prom_tools.prom_query(_prom(), {})
        assert result.status == Status.ERROR
        assert "required" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_query_too_long(self):
        result = await prom_tools.prom_query(_prom(), {"query": "x" * 2001})
        assert result.status == Status.ERROR
        assert "too long" in (result.error_message or "")


class TestPrometheusQuery:
    @pytest.mark.asyncio
    async def test_success_returns_results(self, monkeypatch):
        payload = {"status": "success", "data": {"result": [{"metric": {}, "value": [1, "2"]}]}}
        _install(prom_tools, monkeypatch, _FakeResponse(200, payload))

        result = await prom_tools.prom_query(_prom(), {"query": "up"})

        assert result.status == Status.HEALTHY
        assert result.data["count"] == 1
        url, params, headers = _FakeClient.created[0].requests[0]
        assert url.endswith("/api/v1/query")
        assert params == {"query": "up"}
        assert headers == {"X-Scope-OrgID": "test"}

    @pytest.mark.asyncio
    async def test_http_error_is_reported(self, monkeypatch):
        _install(prom_tools, monkeypatch, _FakeResponse(503, text="unavailable"))

        result = await prom_tools.prom_query(_prom(), {"query": "up"})

        assert result.status == Status.ERROR
        assert "503" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_body_status_error_is_reported(self, monkeypatch):
        _install(prom_tools, monkeypatch, _FakeResponse(200, {"status": "error", "error": "bad"}))

        result = await prom_tools.prom_query(_prom(), {"query": "up"})

        assert result.status == Status.ERROR
        assert "Prometheus error" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_transport_exception_is_reported(self, monkeypatch):
        import httpx

        class _Boom:
            def __init__(self, **kwargs: Any) -> None: ...

            async def __aenter__(self) -> Any:
                raise httpx.ConnectError("connection refused")

            async def __aexit__(self, *exc: Any) -> bool:
                return False

        monkeypatch.setattr(prom_tools.httpx, "AsyncClient", _Boom)

        result = await prom_tools.prom_query(_prom(), {"query": "up"})

        assert result.status == Status.ERROR
        assert "refused" in (result.error_message or "")


class TestPrometheusRange:
    @pytest.mark.asyncio
    async def test_success_passes_window_params(self, monkeypatch):
        payload = {"status": "success", "data": {"result": [{"a": 1}, {"b": 2}]}}
        _install(prom_tools, monkeypatch, _FakeResponse(200, payload))

        result = await prom_tools.prom_range(
            _prom(), {"query": "rate(x[5m])", "start": "-2h", "step": "30s"}
        )

        assert result.status == Status.HEALTHY
        assert result.data["series"] == 2
        assert _FakeClient.created[0].requests[0][1] == {
            "query": "rate(x[5m])",
            "start": "-2h",
            "end": "now",
            "step": "30s",
        }

    @pytest.mark.asyncio
    async def test_http_error(self, monkeypatch):
        _install(prom_tools, monkeypatch, _FakeResponse(500, text="boom"))

        result = await prom_tools.prom_range(_prom(), {"query": "up"})

        assert result.status == Status.ERROR


class TestPrometheusAlerts:
    @pytest.mark.asyncio
    async def test_no_alerts_is_healthy(self, monkeypatch):
        _install(prom_tools, monkeypatch, _FakeResponse(200, {"data": {"alerts": []}}))

        result = await prom_tools.prom_alerts(_prom(), {})

        assert result.status == Status.HEALTHY
        assert result.data == {"total": 0, "firing": 0, "alerts": []}

    @pytest.mark.asyncio
    async def test_firing_alerts_are_degraded(self, monkeypatch):
        alerts = [
            {"state": "firing", "labels": {"alertname": "HighCPU"}},
            {"state": "pending", "labels": {"alertname": "DiskFull"}},
        ]
        _install(prom_tools, monkeypatch, _FakeResponse(200, {"data": {"alerts": alerts}}))

        result = await prom_tools.prom_alerts(_prom(), {})

        assert result.status == Status.DEGRADED
        assert result.data["firing"] == 1
        assert result.suggestions == ["Firing: HighCPU"]

    @pytest.mark.asyncio
    async def test_http_error(self, monkeypatch):
        _install(prom_tools, monkeypatch, _FakeResponse(404, text="not found"))

        result = await prom_tools.prom_alerts(_prom(), {})

        assert result.status == Status.ERROR


class TestPrometheusTargets:
    @pytest.mark.asyncio
    async def test_all_targets_up(self, monkeypatch):
        targets = [{"health": "up", "labels": {"job": "node", "instance": "h:9100"}}]
        _install(prom_tools, monkeypatch, _FakeResponse(200, {"data": {"activeTargets": targets}}))

        result = await prom_tools.prom_targets(_prom(), {})

        assert result.status == Status.HEALTHY
        assert result.data["down"] == 0

    @pytest.mark.asyncio
    async def test_down_targets_are_degraded_with_details(self, monkeypatch):
        targets = [
            {
                "health": "down",
                "labels": {"job": "node", "instance": "db:9100"},
                "lastError": "connect: timeout",
            }
        ]
        _install(prom_tools, monkeypatch, _FakeResponse(200, {"data": {"activeTargets": targets}}))

        result = await prom_tools.prom_targets(_prom(), {})

        assert result.status == Status.DEGRADED
        assert result.data["down_targets"] == [
            {"job": "node", "instance": "db:9100", "last_error": "connect: timeout"}
        ]
        assert result.suggestions == ["1 targets down"]

    @pytest.mark.asyncio
    async def test_http_error(self, monkeypatch):
        _install(prom_tools, monkeypatch, _FakeResponse(502, text="bad gateway"))

        result = await prom_tools.prom_targets(_prom(), {})

        assert result.status == Status.ERROR


class TestLokiValidation:
    @pytest.mark.asyncio
    async def test_query_required(self):
        result = await loki_tools.log_search(_loki(), {})
        assert result.status == Status.ERROR
        assert "required" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_query_too_long(self):
        result = await loki_tools.log_tail(_loki(), {"query": "x" * 2001})
        assert result.status == Status.ERROR
        assert "too long" in (result.error_message or "")


class TestLokiSearch:
    @pytest.mark.asyncio
    async def test_success_flattens_streams(self, monkeypatch):
        payload = {
            "data": {
                "result": [
                    {"stream": {"app": "nginx"}, "values": [["1", "line-1"], ["2", "line-2"]]}
                ]
            }
        }
        _install(loki_tools, monkeypatch, _FakeResponse(200, payload))

        result = await loki_tools.log_search(_loki(), {"query": '{app="nginx"}', "limit": 50})

        assert result.status == Status.HEALTHY
        assert result.data["streams"] == 1
        assert result.data["total_lines"] == 2
        assert result.data["entries"][0] == {"stream": {"app": "nginx"}, "line": "line-1"}
        url, params, _headers = _FakeClient.created[0].requests[0]
        assert url.endswith("/loki/api/v1/query_range")
        assert params["limit"] == 50

    @pytest.mark.asyncio
    async def test_limit_is_clamped_to_minimum(self, monkeypatch):
        _install(loki_tools, monkeypatch, _FakeResponse(200, {"data": {"result": []}}))

        await loki_tools.log_search(_loki(), {"query": '{app="x"}', "limit": 1})

        assert _FakeClient.created[0].requests[0][1]["limit"] == 10

    @pytest.mark.asyncio
    async def test_http_error(self, monkeypatch):
        _install(loki_tools, monkeypatch, _FakeResponse(502, text="bad gateway"))

        result = await loki_tools.log_search(_loki(), {"query": '{app="x"}'})

        assert result.status == Status.ERROR
        assert "502" in (result.error_message or "")


class TestLokiLabels:
    @pytest.mark.asyncio
    async def test_labels_and_values(self, monkeypatch):
        responses = [
            _FakeResponse(200, {"data": ["app", "namespace"]}),
            _FakeResponse(200, {"data": ["nginx", "api"]}),
            _FakeResponse(200, {"data": ["prod"]}),
        ]
        _install(loki_tools, monkeypatch, responses)

        result = await loki_tools.log_labels(_loki(), {})

        assert result.status == Status.HEALTHY
        assert result.data["labels"] == ["app", "namespace"]
        assert result.data["values"] == {"app": ["nginx", "api"], "namespace": ["prod"]}

    @pytest.mark.asyncio
    async def test_label_values_http_error_is_skipped(self, monkeypatch):
        responses = [_FakeResponse(200, {"data": ["app"]}), _FakeResponse(500, text="boom")]
        _install(loki_tools, monkeypatch, responses)

        result = await loki_tools.log_labels(_loki(), {})

        assert result.status == Status.HEALTHY
        assert result.data["values"] == {}

    @pytest.mark.asyncio
    async def test_labels_http_error(self, monkeypatch):
        _install(loki_tools, monkeypatch, _FakeResponse(401, text="unauthorized"))

        result = await loki_tools.log_labels(_loki(), {})

        assert result.status == Status.ERROR


class TestLokiTail:
    @pytest.mark.asyncio
    async def test_success_returns_lines(self, monkeypatch):
        payload = {"data": {"result": [{"stream": {}, "values": [["1", "a"], ["2", "b"]]}]}}
        _install(loki_tools, monkeypatch, _FakeResponse(200, payload))

        result = await loki_tools.log_tail(_loki(), {"query": '{app="x"}', "limit": 20})

        assert result.status == Status.HEALTHY
        assert result.data["lines"] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_http_error(self, monkeypatch):
        _install(loki_tools, monkeypatch, _FakeResponse(500, text="boom"))

        result = await loki_tools.log_tail(_loki(), {"query": '{app="x"}'})

        assert result.status == Status.ERROR
