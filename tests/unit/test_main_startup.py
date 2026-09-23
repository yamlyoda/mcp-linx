"""Wave 12 (B3): старт сервера и цикл завершения в `main.py`.

Покрываем `start_server` (wiring plugin_manager/agent_loop/FastMCP, health-check и
cleanup в `finally`), ветку «сервер завершился первым» в `_main_async` и sync
entrypoint `main()`. Сеть, плагины и MCP не запускаются — только двойники.
"""

from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass
from typing import Any

import pytest

# NB: `import mcp_linx.main as m` вернул бы ФУНКЦИЮ (shadowing в `__init__.py`).
m = importlib.import_module("mcp_linx.main")


@dataclass
class _FakeMCP:
    name: str
    version: str | None = None


class _FakeLoop:
    def __init__(self, calls: dict[str, Any]) -> None:
        self._calls = calls

    async def setup(self, mcp: Any, plugin_manager: Any, config: dict[str, Any]) -> None:
        self._calls["setup"] = (mcp, config)

    async def run(self, mcp: Any, plugin_manager: Any, config: dict[str, Any]) -> None:
        self._calls["run"] = True

    async def shutdown(self, mcp: Any, plugin_manager: Any) -> None:
        self._calls["shutdown"] = True


class _FakeManager:
    instances: list[_FakeManager] = []

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.loaded = False
        self.health_calls = 0
        self.health_error: Exception | None = None
        type(self).instances.append(self)

    def load_plugins(self) -> None:
        self.loaded = True

    async def health_check_all(self) -> dict[str, Any]:
        self.health_calls += 1
        if self.health_error is not None:
            raise self.health_error
        return {}


@pytest.fixture()
def wired(monkeypatch):
    """Подменить внешние зависимости `start_server` и собрать вызовы."""
    calls: dict[str, Any] = {}
    _FakeManager.instances.clear()

    monkeypatch.setattr(m, "load_config", lambda path: {"config_path": path})
    monkeypatch.setattr(m, "discover_plugins", lambda: 10)
    monkeypatch.setattr(m, "PluginManager", _FakeManager)
    monkeypatch.setattr(m, "FastMCP", _FakeMCP)
    monkeypatch.setattr(m, "get_agent_loop", lambda loop_type: _FakeLoop(calls))
    return calls


class TestStartServer:
    @pytest.mark.asyncio
    async def test_wires_config_manager_loop_and_cleanup(self, wired):
        await m.start_server()

        manager = _FakeManager.instances[-1]
        assert manager.loaded is True
        assert manager.health_calls == 1
        assert "setup" in wired and "run" in wired
        assert wired["shutdown"] is True
        mcp, config = wired["setup"]
        assert isinstance(mcp, _FakeMCP)
        assert config == {"config_path": m.settings.config_path}

    @pytest.mark.asyncio
    async def test_health_check_failure_is_logged_not_fatal(self, wired, monkeypatch):
        class _FlakyManager(_FakeManager):
            def __init__(self, config: dict[str, Any]) -> None:
                super().__init__(config)
                self.health_error = RuntimeError("health backend down")

        monkeypatch.setattr(m, "PluginManager", _FlakyManager)

        await m.start_server()  # не должно бросить

        assert wired["run"] is True
        assert wired["shutdown"] is True

    @pytest.mark.asyncio
    async def test_shutdown_runs_even_if_run_fails(self, wired, monkeypatch):
        class _FailingLoop(_FakeLoop):
            async def run(self, mcp: Any, plugin_manager: Any, config: dict[str, Any]) -> None:
                raise RuntimeError("transport died")

        monkeypatch.setattr(m, "get_agent_loop", lambda loop_type: _FailingLoop(wired))

        with pytest.raises(RuntimeError, match="transport died"):
            await m.start_server()

        assert wired["shutdown"] is True


class TestMainAsyncCompletion:
    @pytest.mark.asyncio
    async def test_server_finishing_first_cancels_stop_task(self, monkeypatch):
        """Ветка else: start_server вернулся раньше сигнала — stop_task отменяется."""
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "add_signal_handler", lambda *args, **kwargs: None)

        async def _instant() -> None:
            return None

        monkeypatch.setattr(m, "start_server", _instant)

        await m._main_async()  # должно завершиться без зависаний и исключений


class TestSyncEntrypoint:
    def test_main_runs_async_entrypoint(self, monkeypatch):
        called: list[bool] = []

        async def _fake() -> None:
            called.append(True)

        monkeypatch.setattr(m, "_main_async", _fake)

        m.main()

        assert called == [True]
