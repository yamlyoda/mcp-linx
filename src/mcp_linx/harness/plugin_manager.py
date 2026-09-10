"""Менеджер плагинов с автообнаружением.

Реализует идеологию Harness: плагины обнаруживаются автоматически
и могут быть заменены через конфигурацию.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

from mcp_linx.types import HealthStatus, PluginConfig, Status
from mcp_linx.plugins.base import DiagnosticPlugin

logger = logging.getLogger(__name__)

# Реестр плагинов: id -> класс
PLUGIN_REGISTRY: dict[str, type[DiagnosticPlugin]] = {}


def register_plugin(plugin_class: type[DiagnosticPlugin]) -> None:
    """Зарегистрировать плагин в менеджере."""
    instance = plugin_class()
    PLUGIN_REGISTRY[instance.id] = plugin_class
    logger.info(f"Plugin registered: {instance.id} ({instance.name})")


def get_plugin(plugin_id: str) -> DiagnosticPlugin | None:
    """Получить экземпляр плагина по ID."""
    plugin_class = PLUGIN_REGISTRY.get(plugin_id)
    if plugin_class:
        return plugin_class()
    return None


def discover_plugins() -> int:
    """Автообнаружение плагинов в директории plugins/.

    Сканирует директорию src/mcp_linx/plugins/ и автоматически
    регистрирует все классы, наследующиеся от DiagnosticPlugin.

    Returns:
        Количество обнаруженных плагинов
    """
    plugins_dir = Path(__file__).parent.parent / "plugins"
    discovered = 0

    if not plugins_dir.exists():
        logger.warning(f"Plugins directory not found: {plugins_dir}")
        return 0

    for plugin_dir in plugins_dir.iterdir():
        if not plugin_dir.is_dir():
            continue

        init_file = plugin_dir / "__init__.py"
        if not init_file.exists():
            continue

        module_name = f"mcp_linx.plugins.{plugin_dir.name}"

        try:
            module = importlib.import_module(module_name)

            for attr_name in dir(module):
                attr = getattr(module, attr_name)

                if (
                    isinstance(attr, type)
                    and issubclass(attr, DiagnosticPlugin)
                    and attr is not DiagnosticPlugin
                ):
                    register_plugin(attr)
                    discovered += 1

        except Exception as e:
            logger.error(f"Failed to import {module_name}: {e}")

    logger.info(f"Discovered {discovered} plugins")
    return discovered


class PluginManager:
    """Менеджер плагинов — загрузка, инициализация, health check, уничтожение.

    Поддерживает:
    - Автообнаружение плагинов
    - Фильтрацию по enabled в конфиге
    - Управление жизненным циклом
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}
        self._plugins: dict[str, DiagnosticPlugin] = {}
        self._initialized = False

    def load_plugins(self) -> None:
        """Загрузить все зарегистрированные плагины."""
        for plugin_id, plugin_class in PLUGIN_REGISTRY.items():
            try:
                plugin = plugin_class()
                self._plugins[plugin_id] = plugin
                logger.info(f"Plugin loaded: {plugin_id}")
            except Exception as e:
                logger.error(f"Failed to load plugin {plugin_id}: {e}")

    def get_plugin(self, plugin_id: str) -> DiagnosticPlugin | None:
        """Получить плагин по ID."""
        return self._plugins.get(plugin_id)

    def get_all_plugins(self) -> list[DiagnosticPlugin]:
        """Получить все загруженные плагины."""
        return list(self._plugins.values())

    def get_enabled_plugins(self) -> list[DiagnosticPlugin]:
        """Получить только включенные плагины согласно конфигурации."""
        enabled_ids = set(self._config.get("plugins", {}).get("enabled", []))
        if not enabled_ids:
            return list(self._plugins.values())
        return [p for pid, p in self._plugins.items() if pid in enabled_ids]

    async def initialize_all(self) -> None:
        """Инициализировать все включенные плагины."""
        if self._initialized:
            return

        enabled_plugins = self.get_enabled_plugins()

        # Глобальная security-секция из settings.yaml (если есть)
        global_security = self._config.get("security", {})
        if not isinstance(global_security, dict):
            global_security = {}

        for plugin in enabled_plugins:
            try:
                plugin_config_dict = dict(self._config.get("plugins", {}).get(plugin.id, {}))
                # Пробрасываем глобальные security-настройки под ключ "security",
                # если плагин не задал свои
                if global_security:
                    plugin_config_dict.setdefault("security", dict(global_security))
                await plugin.initialize(PluginConfig(plugin_config_dict))
                logger.info(f"Plugin initialized: {plugin.id}")
            except Exception as e:
                logger.error(f"Failed to initialize plugin {plugin.id}: {e}")
                # Don't raise - allow other plugins to initialize
                # Plugin will be unavailable but server continues

        self._initialized = True

    async def health_check_all(self) -> dict[str, HealthStatus]:
        """Выполнить health check всех плагинов."""
        results: dict[str, HealthStatus] = {}

        for plugin_id, plugin in self._plugins.items():
            try:
                status = await plugin.health_check()
                results[plugin_id] = status
                logger.info(f"Health check {plugin_id}: {status.status.value}")
            except Exception as e:
                results[plugin_id] = HealthStatus(Status.ERROR, str(e))
                logger.error(f"Health check failed for {plugin_id}: {e}")

        return results

    async def destroy_all(self) -> None:
        """Уничтожить все плагины (закрыть соединения)."""
        for plugin_id, plugin in self._plugins.items():
            try:
                await plugin.destroy()
                logger.info(f"Plugin destroyed: {plugin_id}")
            except Exception as e:
                logger.error(f"Failed to destroy plugin {plugin_id}: {e}")

        self._plugins.clear()
        self._initialized = False

    def get_tools(self) -> list[dict[str, Any]]:
        """Получить все инструменты всех плагинов для регистрации в MCP."""
        tools: list[dict[str, Any]] = []

        for plugin_id, plugin in self._plugins.items():
            for tool in plugin.get_tools():
                tools.append({
                    "name": tool.name,
                    "description": tool.description,
                    "plugin_id": plugin_id,
                    "execute": tool.execute,
                })

        return tools
