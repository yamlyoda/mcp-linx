"""Wave 6: `plugins.enabled` — активный набор плагинов (load/init/tools/health/destroy).

Тесты изолированы: `PLUGIN_REGISTRY` подменяется фиктивными плагинами, реальная
инфраструктура (SSH/Docker/PG) не используется.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from mcp_linx.plugins.base import DiagnosticPlugin, PluginTool
from mcp_linx.types import HealthStatus, PluginConfig, Status

FAKE_IDS = ("linux", "nginx", "redis")


class _FakePlugin(DiagnosticPlugin):
    """Плагин без инфраструктуры: 1 tool, счётчики initialize/destroy."""

    id = "fake"
    name = "fake"
    tools = [PluginTool("probe", "probe")]

    def __init__(self) -> None:
        self.initialize_calls = 0
        self.destroy_calls = 0

    async def initialize(self, config: PluginConfig) -> None:
        self.initialize_calls += 1

    async def health_check(self) -> HealthStatus:
        return HealthStatus(Status.HEALTHY, "ok")

    async def destroy(self) -> None:
        self.destroy_calls += 1


def _fake_class(plugin_id: str) -> type[DiagnosticPlugin]:
    """Класс-плагин с заданным id (конструктор без аргументов)."""
    return type(f"Fake_{plugin_id}", (_FakePlugin,), {"id": plugin_id, "name": plugin_id})


@pytest.fixture()
def pm(monkeypatch):
    """Модуль plugin_manager с изолированным реестром linux/nginx/redis."""
    import mcp_linx.harness.plugin_manager as module

    fake_registry = {pid: _fake_class(pid) for pid in FAKE_IDS}
    monkeypatch.setattr(module, "PLUGIN_REGISTRY", fake_registry)
    return module


def _loaded_ids(manager) -> set[str]:
    return {plugin.id for plugin in manager.get_all_plugins()}


class TestEnabledSelection:
    def test_subset_loads_only_listed(self, pm):
        manager = pm.PluginManager({"plugins": {"enabled": ["linux", "redis"]}})

        manager.load_plugins()

        assert _loaded_ids(manager) == {"linux", "redis"}

    def test_subset_limits_tools_and_health_check(self, pm):
        manager = pm.PluginManager({"plugins": {"enabled": ["linux"]}})
        manager.load_plugins()

        tools = manager.get_tools()
        assert [t["plugin_id"] for t in tools] == ["linux"]

    @pytest.mark.asyncio
    async def test_health_check_covers_only_active(self, pm):
        manager = pm.PluginManager({"plugins": {"enabled": ["linux", "redis"]}})
        manager.load_plugins()

        results = await manager.health_check_all()

        assert set(results) == {"linux", "redis"}

    def test_absent_enabled_loads_all(self, pm):
        manager = pm.PluginManager({})

        manager.load_plugins()

        assert _loaded_ids(manager) == set(FAKE_IDS)

    def test_empty_enabled_loads_all(self, pm):
        manager = pm.PluginManager({"plugins": {"enabled": []}})

        manager.load_plugins()

        assert _loaded_ids(manager) == set(FAKE_IDS)

    def test_non_dict_plugins_section_loads_all(self, pm):
        """Некорректная секция `plugins` не должна молча отключать всё."""
        manager = pm.PluginManager({"plugins": "oops"})

        manager.load_plugins()

        assert _loaded_ids(manager) == set(FAKE_IDS)

    def test_unknown_id_is_skipped_with_warning(self, pm, caplog):
        manager = pm.PluginManager({"plugins": {"enabled": ["linux", "typo"]}})

        with caplog.at_level(logging.WARNING, logger="mcp_linx.harness.plugin_manager"):
            manager.load_plugins()

        assert _loaded_ids(manager) == {"linux"}
        assert any("typo" in record.message for record in caplog.records)

    def test_get_enabled_plugins_matches_loaded_set(self, pm):
        manager = pm.PluginManager({"plugins": {"enabled": ["nginx"]}})
        manager.load_plugins()

        assert {p.id for p in manager.get_enabled_plugins()} == {"nginx"}


class TestLifecycleScope:
    @pytest.mark.asyncio
    async def test_initialize_all_touches_only_active(self, pm):
        manager = pm.PluginManager({"plugins": {"enabled": ["linux"]}})
        manager.load_plugins()

        await manager.initialize_all()

        plugin = manager.get_plugin("linux")
        assert plugin is not None
        assert plugin.initialize_calls == 1

    @pytest.mark.asyncio
    async def test_destroy_all_touches_only_active(self, pm):
        manager = pm.PluginManager({"plugins": {"enabled": ["linux"]}})
        manager.load_plugins()
        plugin = manager.get_plugin("linux")

        await manager.destroy_all()

        assert plugin is not None
        assert plugin.destroy_calls == 1
        assert manager.get_all_plugins() == []


class TestShippedConfig:
    def test_settings_enable_every_discovered_plugin(self):
        """`config/settings.yaml` не должен отставать от набора плагинов в src.

        Если добавили директорию плагина, но забыли `plugins.enabled`, его tools
        молча исчезнут — этот тест падает раньше.
        """
        from mcp_linx.harness.plugin_manager import PLUGIN_REGISTRY, PluginManager, discover_plugins

        repo_root = Path(__file__).resolve().parents[2]
        config = yaml.safe_load((repo_root / "config" / "settings.yaml").read_text())

        discover_plugins()
        manager = PluginManager(config)
        manager.load_plugins()

        assert _loaded_ids(manager) == set(PLUGIN_REGISTRY), (
            "plugins.enabled в config/settings.yaml разошёлся с реестром плагинов: "
            f"загружено {sorted(_loaded_ids(manager))}, зарегистрировано {sorted(PLUGIN_REGISTRY)}"
        )
