"""B1: ядро оркестрации — `DefaultAgentLoop._make_handler`.

Покрываем: rate-limit → error-ответ, добавление `metadata`, обновление
`ContextAggregator`, audit в `finally` (включая ветку без `status`),
обёртку исключений и требование `setup()`.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from mcp_linx.context_aggregator import ContextAggregator
from mcp_linx.harness.agent_loop import DefaultAgentLoop
from mcp_linx.ratelimit import RateLimiter
from mcp_linx.types import Status, ToolResult


class _PluginStub:
    """Минимальный плагин: обработчику нужен только `id`."""

    id = "stub"


def _loop(
    audit_logger: Any = None,
    rate_limiter: RateLimiter | None = None,
) -> DefaultAgentLoop:
    loop = DefaultAgentLoop()
    loop._context_aggregator = ContextAggregator()
    loop._audit_logger = audit_logger
    loop._rate_limiter = rate_limiter
    return loop


class TestHandlerSuccessPath:
    @pytest.mark.asyncio
    async def test_metadata_and_context_updated(self):
        async def execute(plugin: Any, params: dict[str, Any]) -> ToolResult:
            assert params == {"host": "localhost"}
            return ToolResult.ok({"x": 1}, metadata={"existing": "keep"})

        loop = _loop()
        handler = loop._make_handler(_PluginStub(), "stub_tool", execute)

        result = await handler({"host": "localhost"})

        # metadata из ToolResult сохранена, plugin/tool добавлены
        assert result["metadata"] == {"existing": "keep", "plugin": "stub", "tool": "stub_tool"}
        assert result["status"] == "healthy"
        # контекст обновлён состоянием инструмента
        components = loop._context_aggregator.get_components()
        assert [c.plugin_id for c in components] == ["stub"]
        assert components[0].status == Status.HEALTHY

    @pytest.mark.asyncio
    async def test_plain_dict_result_gets_metadata(self):
        async def execute(plugin: Any, params: dict[str, Any]) -> dict[str, Any]:
            return {"status": "degraded", "data": [1]}

        loop = _loop()
        handler = loop._make_handler(_PluginStub(), "stub_tool", execute)

        result = await handler(None)  # params=None → {}

        assert result["metadata"] == {"plugin": "stub", "tool": "stub_tool"}
        assert result["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_result_without_status_yields_unknown_in_audit(self):
        """Ветка `status if "status" in locals() else "error"` в finally."""

        async def execute(plugin: Any, params: dict[str, Any]) -> dict[str, Any]:
            return {"data": "no status key"}

        audit = MagicMock()
        loop = _loop(audit_logger=audit)
        handler = loop._make_handler(_PluginStub(), "stub_tool", execute)

        result = await handler({})

        # dict возвращается как есть (status хендлер не достраивает),
        # но в audit фиксируется "unknown"
        assert "status" not in result
        assert result["data"] == "no status key"
        assert audit.log_call.call_args.kwargs["status"] == "unknown"
        # контекст не обновляется для dict без status/suggestions
        assert loop._context_aggregator.get_components() == []


class TestHandlerRateLimit:
    @pytest.mark.asyncio
    async def test_limit_exceeded_returns_error_without_executing(self):
        executed: list[dict[str, Any]] = []

        async def execute(plugin: Any, params: dict[str, Any]) -> ToolResult:
            executed.append(params)
            return ToolResult.ok({})

        audit = MagicMock()
        loop = _loop(audit_logger=audit, rate_limiter=RateLimiter(max_calls=1, window_seconds=60))
        handler = loop._make_handler(_PluginStub(), "stub_tool", execute)

        first = await handler({})
        second = await handler({})

        assert first["status"] == "healthy"
        assert second["status"] == "error"
        assert "Rate limit exceeded" in second["error_message"]
        assert second["metadata"] == {"plugin": "stub", "tool": "stub_tool"}
        # второй вызов до execute_func не дошёл
        assert len(executed) == 1
        # Отказ по rate-limit тоже аудируется: проверка перенесена внутрь try/finally.
        assert audit.log_call.call_count == 2
        assert audit.log_call.call_args.kwargs["status"] == "error"
        assert "Rate limit exceeded" in audit.log_call.call_args.kwargs["error"]


class TestHandlerErrorPath:
    @pytest.mark.asyncio
    async def test_exception_is_wrapped_and_audited(self):
        async def execute(plugin: Any, params: dict[str, Any]) -> ToolResult:
            raise RuntimeError("tool blew up")

        audit = MagicMock()
        loop = _loop(audit_logger=audit)
        handler = loop._make_handler(_PluginStub(), "stub_tool", execute)

        result = await handler(None)

        assert result == {
            "status": "error",
            "error_message": "tool blew up",
            "metadata": {"plugin": "stub", "tool": "stub_tool"},
        }
        assert audit.log_call.call_args.kwargs["error"] == "tool blew up"
        assert audit.log_call.call_args.kwargs["tool_name"] == "stub_tool"
        assert audit.log_call.call_args.kwargs["plugin_id"] == "stub"
        assert audit.log_call.call_args.kwargs["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_handler_works_without_audit_logger(self):
        async def execute(plugin: Any, params: dict[str, Any]) -> ToolResult:
            return ToolResult.ok({"ok": True})

        loop = _loop(audit_logger=None)
        handler = loop._make_handler(_PluginStub(), "stub_tool", execute)

        result = await handler({})

        assert result["status"] == "healthy"
        assert result["metadata"]["plugin"] == "stub"


class TestHandlerRequiresSetup:
    def test_make_handler_before_setup_raises(self):
        loop = DefaultAgentLoop()  # _context_aggregator is None

        with pytest.raises(RuntimeError, match="ContextAggregator is not initialized"):
            loop._make_handler(_PluginStub(), "stub_tool", lambda p, q: None)
