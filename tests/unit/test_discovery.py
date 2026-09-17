"""B5: дрейф счётчиков плагинов/инструментов (точные значения вместо `>=`)."""

from __future__ import annotations

EXPECTED_PLUGINS = 10
EXPECTED_TOOLS = 56


def _discovery_counts() -> tuple[int, int]:
    from mcp_linx.harness.plugin_manager import PluginManager, discover_plugins

    plugins = discover_plugins()
    manager = PluginManager({})
    manager.load_plugins()
    return plugins, len(manager.get_tools())


def test_discovered_plugins_count_is_exact():
    plugins, _ = _discovery_counts()
    assert plugins == EXPECTED_PLUGINS, (
        f"plugin count drift: {plugins} != {EXPECTED_PLUGINS} — "
        "если это осознанное изменение, обнови EXPECTED_PLUGINS здесь и в .github/workflows/ci.yml"
    )


def test_registered_tools_count_is_exact():
    _, tools = _discovery_counts()
    assert tools == EXPECTED_TOOLS, (
        f"tool count drift: {tools} != {EXPECTED_TOOLS} — "
        "если это осознанное изменение, обнови EXPECTED_TOOLS здесь и в .github/workflows/ci.yml"
    )
