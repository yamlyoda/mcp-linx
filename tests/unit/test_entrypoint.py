"""Тесты точек входа: sync main(), __main__.py, обработка сигналов (A1/A2)."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import signal
import textwrap

import pytest


def test_main_is_sync_entrypoint():
    """A1: console script требует sync-функцию (async main ломал .venv/bin/mcp-linx)."""
    from mcp_linx.main import main

    assert not inspect.iscoroutinefunction(main)


def test_package_main_module_exists():
    """A1: python -m mcp_linx должен работать (раньше не было __main__.py)."""
    import mcp_linx.__main__ as pkg_main

    assert callable(getattr(pkg_main, "main", None))


@pytest.mark.asyncio
async def test_sigterm_triggers_shutdown(monkeypatch):
    """A2: SIGTERM должен отменять серверную задачу (раньше хендлер был no-op)."""
    import importlib

    # NB: `import mcp_linx.main as m` возвращает ФУНКЦИЮ main, а не модуль —
    # __init__.py затеняет submodule (см. A1). Берём модуль через importlib.
    main_pkg = importlib.import_module("mcp_linx.main")

    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def fake_server():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(main_pkg, "start_server", fake_server)

    task = asyncio.create_task(main_pkg._main_async())
    await asyncio.wait_for(started.wait(), timeout=5)
    loop = asyncio.get_running_loop()
    # Эмулируем доставку SIGTERM через зарегистрированный хендлер.
    # NB: loop._signal_handlers хранит Handle-объекты — вызываем их _callback.
    handlers = {
        sig: loop._signal_handlers.get(sig)  # type: ignore[attr-defined]
        for sig in (signal.SIGTERM, signal.SIGINT)
    }
    assert any(h is not None for h in handlers.values()), "signal handlers not registered"
    for h in handlers.values():
        if h is not None:
            h._callback(*h._args)  # type: ignore[union-attr]
            break
    await asyncio.wait_for(task, timeout=5)
    assert cancelled.is_set(), "server task was not cancelled on signal"


class TestEnvSubstitution:
    """A4: ${VAR} / ${VAR:-default} в YAML раскрываются из env при загрузке."""

    def _write_cfg(self, tmp_path, body: str) -> str:
        p = tmp_path / "settings.yaml"
        p.write_text(textwrap.dedent(body), encoding="utf-8")
        return str(p)

    def test_var_expands_from_env(self, tmp_path, monkeypatch):
        main_pkg = importlib.import_module("mcp_linx.main")
        monkeypatch.setenv("MCP_LINX_TEST_PW", "s3cret")
        path = self._write_cfg(
            tmp_path, 'plugins:\n  postgres:\n    password: "${MCP_LINX_TEST_PW}"\n'
        )
        cfg = main_pkg.load_config(path)
        assert cfg["plugins"]["postgres"]["password"] == "s3cret"

    def test_default_used_when_missing(self, tmp_path, monkeypatch):
        main_pkg = importlib.import_module("mcp_linx.main")
        monkeypatch.delenv("MCP_LINX_TEST_MISSING", raising=False)
        path = self._write_cfg(tmp_path, 'token: "${MCP_LINX_TEST_MISSING:-fallback}"\n')
        cfg = main_pkg.load_config(path)
        assert cfg["token"] == "fallback"

    def test_missing_without_default_falls_back_to_raw(self, tmp_path, monkeypatch, caplog):
        main_pkg = importlib.import_module("mcp_linx.main")
        monkeypatch.delenv("MCP_LINX_TEST_MISSING", raising=False)
        path = self._write_cfg(tmp_path, 'token: "${MCP_LINX_TEST_MISSING}"\n')
        with caplog.at_level("WARNING", logger="mcp_linx"):
            cfg = main_pkg.load_config(path)
        # fail-open в raw: подстановка не выполнена, но загрузка не падает
        assert cfg["token"] == "${MCP_LINX_TEST_MISSING}"
        assert any("env-substitution" in r.message for r in caplog.records)

    def test_default_config_loads(self):
        # Реальный settings.yaml с ${...:-} обязан грузиться без env
        main_pkg = importlib.import_module("mcp_linx.main")
        cfg = main_pkg.load_config("config/settings.yaml")
        assert cfg["plugins"]["postgres"]["password"] == ""


class TestAllowedHosts:
    """A3: передача host сверяется с allowed_hosts до резолва адаптера."""

    @pytest.mark.asyncio
    async def test_host_not_in_whitelist_blocked(self):
        from mcp_linx.plugins.linux import LinuxPlugin

        plugin = LinuxPlugin()
        # PluginConfig — обычный dict; дефолты (таймауты, размеры) берутся из .get()
        await plugin.initialize({})
        # Подменяем security на whitelist без web-1
        from mcp_linx.security import SecurityError, SecurityGuard

        plugin._security = SecurityGuard({"allowed_hosts": ["localhost"]})

        with pytest.raises(SecurityError, match="not in allowed_hosts"):
            await plugin._run_command("uptime", host="web-1")

    @pytest.mark.asyncio
    async def test_empty_whitelist_allows_any(self, monkeypatch):
        from mcp_linx.plugins.linux import LinuxPlugin

        plugin = LinuxPlugin()
        await plugin.initialize({})
        from mcp_linx.security import SecurityGuard

        plugin._security = SecurityGuard({"allowed_hosts": []})

        async def fake_exec(cmd, timeout):
            return {"stdout": "ok", "stderr": "", "returncode": 0}

        class FakeRegistry:
            def get_adapter(self, name):
                return type("A", (), {"execute_command": staticmethod(fake_exec)})()

        plugin.hosts = FakeRegistry()  # type: ignore[assignment]
        result = await plugin._run_command("uptime", host="web-1")
        assert result["stdout"] == "ok"
