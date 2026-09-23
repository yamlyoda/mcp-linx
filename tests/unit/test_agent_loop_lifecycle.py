"""Wave 12 (B1): жизненный цикл `DefaultAgentLoop`/`StreamingAgentLoop`.

Покрываем `setup` / `run` / `shutdown`, регистрацию плагинных и системных
инструментов, инжект `HostRegistry` и автосбор контекста из health check.
`FastMCP` и `PluginManager` подменяются — сети и инфраструктуры нет.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from mcp_linx.harness.agent_loop import DefaultAgentLoop, StreamingAgentLoop
from mcp_linx.plugins.base import PluginTool
from mcp_linx.types import HealthStatus, Status, ToolResult


class _FakeMCP:
    """Минимальный FastMCP: собирает зарегистрированные инструменты."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}
        self.descriptions: dict[str, str] = {}
        self.run_calls = 0

    def tool(self, name: str | None = None, description: str | None = None):
        def decorator(fn: Any) -> Any:
            assert name is not None
            self.tools[name] = fn
            self.descriptions[name] = description or ""
            return fn

        return decorator

    async def run_async(self) -> None:
        self.run_calls += 1


class _FakePlugin:
    def __init__(self, plugin_id: str) -> None:
        self.id = plugin_id
        self.hosts: Any = None

    def get_tools(self) -> list[PluginTool]:
        return [PluginTool("probe", "probe tool")]


class _FakeManager:
    """PluginManager-совместимый двойник, считающий вызовы жизненного цикла."""

    def __init__(
        self,
        plugins: list[_FakePlugin] | None = None,
        tools: list[dict[str, Any]] | None = None,
        health: dict[str, HealthStatus] | None = None,
        health_error: Exception | None = None,
    ) -> None:
        self._plugins = {p.id: p for p in (plugins or [])}
        self._tools = tools or []
        self._health = health or {}
        self.health_error = health_error
        self.initialize_calls = 0
        self.destroy_calls = 0

    async def initialize_all(self) -> None:
        self.initialize_calls += 1

    def get_all_plugins(self) -> list[_FakePlugin]:
        return list(self._plugins.values())

    def get_tools(self) -> list[dict[str, Any]]:
        return self._tools

    def get_plugin(self, plugin_id: str) -> _FakePlugin | None:
        return self._plugins.get(plugin_id)

    async def health_check_all(self) -> dict[str, HealthStatus]:
        if self.health_error is not None:
            raise self.health_error
        return self._health

    async def destroy_all(self) -> None:
        self.destroy_calls += 1


async def _exec_ok(plugin: Any, params: dict[str, Any]) -> ToolResult:
    return ToolResult.ok({"seen": params})


def _manager_with_tool(plugin_id: str = "linux", tool_name: str = "linux_probe") -> _FakeManager:
    plugin = _FakePlugin(plugin_id)
    tool = {
        "name": tool_name,
        "description": "probe",
        "plugin_id": plugin_id,
        "execute": _exec_ok,
    }
    return _FakeManager(plugins=[plugin], tools=[tool])


async def loop_setup(loop: Any, mcp: _FakeMCP, manager: _FakeManager) -> None:
    """Хелпер: `setup` с типизированными двойниками."""
    await loop.setup(mcp, manager, {})


class TestSetup:
    @pytest.mark.asyncio
    async def test_registers_plugin_and_system_tools(self):
        manager = _manager_with_tool()
        mcp = _FakeMCP()

        await loop_setup(DefaultAgentLoop(), mcp, manager)

        assert "linux_probe" in mcp.tools
        assert {"get_diagnostic_context", "get_summary", "system_health_check"} <= set(mcp.tools)
        assert mcp.descriptions["linux_probe"] == "probe"
        assert manager.initialize_calls == 1

    @pytest.mark.asyncio
    async def test_injects_host_registry_into_plugins(self):
        manager = _manager_with_tool()
        loop = DefaultAgentLoop()

        await loop_setup(loop, _FakeMCP(), manager)

        plugin = manager.get_all_plugins()[0]
        assert plugin.hosts is loop._host_registry
        assert plugin.hosts is not None
        assert plugin.hosts.list_hosts() == []

    @pytest.mark.asyncio
    async def test_configured_hosts_are_available_in_registry(self):
        manager = _manager_with_tool()
        config = {"hosts": {"web-1": {"host": "10.0.0.1"}}}

        await DefaultAgentLoop().setup(_FakeMCP(), manager, config)

        plugin = manager.get_all_plugins()[0]
        assert plugin.hosts is not None
        assert plugin.hosts.list_hosts() == ["web-1"]

    @pytest.mark.asyncio
    async def test_tool_for_unknown_plugin_is_skipped(self):
        plugin = _FakePlugin("linux")
        tool = {
            "name": "ghost_tool",
            "description": "ghost",
            "plugin_id": "ghost",
            "execute": _exec_ok,
        }
        manager = _FakeManager(plugins=[plugin], tools=[tool])
        mcp = _FakeMCP()

        await loop_setup(DefaultAgentLoop(), mcp, manager)

        assert "ghost_tool" not in mcp.tools

    @pytest.mark.asyncio
    async def test_health_seeding_adds_component_with_issues(self):
        manager = _manager_with_tool()
        manager._health = {"linux": HealthStatus(Status.UNHEALTHY, "service down")}
        loop = DefaultAgentLoop()

        await loop_setup(loop, _FakeMCP(), manager)

        components = loop._context_aggregator.get_components()
        assert [c.plugin_id for c in components] == ["linux"]
        assert components[0].issues == ["service down"]

    @pytest.mark.asyncio
    async def test_healthy_plugin_has_no_issues(self):
        manager = _manager_with_tool()
        manager._health = {"linux": HealthStatus(Status.HEALTHY, "ok")}
        loop = DefaultAgentLoop()

        await loop_setup(loop, _FakeMCP(), manager)

        components = loop._context_aggregator.get_components()
        assert components[0].issues is None

    @pytest.mark.asyncio
    async def test_health_failure_does_not_break_setup(self):
        manager = _manager_with_tool()
        manager.health_error = RuntimeError("health backend down")
        loop = DefaultAgentLoop()

        await loop_setup(loop, _FakeMCP(), manager)  # не должно бросить

        assert loop._context_aggregator is not None

    @pytest.mark.asyncio
    async def test_seed_without_aggregator_is_noop(self):
        loop = DefaultAgentLoop()

        await loop._seed_context_from_health(_manager_with_tool())


class TestRunAndShutdown:
    @pytest.mark.asyncio
    async def test_run_calls_run_async(self):
        mcp = _FakeMCP()

        await DefaultAgentLoop().run(mcp, _manager_with_tool(), {})

        assert mcp.run_calls == 1

    @pytest.mark.asyncio
    async def test_streaming_run_calls_run_async(self):
        mcp = _FakeMCP()

        await StreamingAgentLoop().run(mcp, _manager_with_tool(), {})

        assert mcp.run_calls == 1

    @pytest.mark.asyncio
    async def test_shutdown_destroys_plugins_and_closes_hosts(self):
        manager = _manager_with_tool()
        loop = DefaultAgentLoop()
        await loop_setup(loop, _FakeMCP(), manager)
        registry = MagicMock()
        loop._host_registry = registry

        await loop.shutdown(_FakeMCP(), manager)

        assert manager.destroy_calls == 1
        registry.close_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_without_host_registry(self):
        manager = _manager_with_tool()

        await DefaultAgentLoop().shutdown(_FakeMCP(), manager)

        assert manager.destroy_calls == 1

    @pytest.mark.asyncio
    async def test_streaming_shutdown_closes_hosts(self):
        manager = _manager_with_tool()
        loop = StreamingAgentLoop()
        registry = MagicMock()
        loop._host_registry = registry

        await loop.shutdown(_FakeMCP(), manager)

        assert manager.destroy_calls == 1
        registry.close_all.assert_called_once()


class TestRegisteredToolCall:
    @pytest.mark.asyncio
    async def test_plugin_tool_handler_adds_metadata(self):
        manager = _manager_with_tool()
        mcp = _FakeMCP()
        await loop_setup(DefaultAgentLoop(), mcp, manager)

        result = await mcp.tools["linux_probe"]({"host": "web-1"})

        assert result["status"] == "healthy"
        assert result["data"] == {"seen": {"host": "web-1"}}
        assert result["metadata"]["plugin"] == "linux"
        assert result["metadata"]["tool"] == "linux_probe"


class TestSystemTools:
    @pytest.mark.asyncio
    async def test_get_diagnostic_context_shape(self):
        mcp = _FakeMCP()
        await loop_setup(DefaultAgentLoop(), mcp, _manager_with_tool())

        context = await mcp.tools["get_diagnostic_context"]()

        assert set(context) == {"timestamp", "host_id", "components", "correlations"}
        assert context["host_id"] == "localhost"

    @pytest.mark.asyncio
    async def test_get_summary_delegates_to_aggregator(self):
        mcp = _FakeMCP()
        await loop_setup(DefaultAgentLoop(), mcp, _manager_with_tool())

        summary = await mcp.tools["get_summary"]()

        assert isinstance(summary, dict)

    @pytest.mark.asyncio
    async def test_system_health_check_reports_healthy(self):
        manager = _manager_with_tool()
        manager._health = {"linux": HealthStatus(Status.HEALTHY, "fine")}
        mcp = _FakeMCP()
        loop = DefaultAgentLoop()
        await loop_setup(loop, mcp, manager)

        result = await mcp.tools["system_health_check"]()

        assert result["status"] == "healthy"
        assert result["results"] == {"linux": {"status": "healthy", "message": "fine"}}
        assert loop._context_aggregator is not None
        assert loop._context_aggregator.get_component("linux") is not None

    @pytest.mark.asyncio
    async def test_system_health_check_reports_degraded_with_issues(self):
        manager = _manager_with_tool()
        manager._health = {"linux": HealthStatus(Status.ERROR, "boom")}
        mcp = _FakeMCP()
        loop = DefaultAgentLoop()
        await loop_setup(loop, mcp, manager)

        result = await mcp.tools["system_health_check"]()

        assert result["status"] == "degraded"
        assert loop._context_aggregator is not None
        component = loop._context_aggregator.get_component("linux")
        assert component is not None
        assert component.issues == ["boom"]
