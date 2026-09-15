"""Базовые классы для плагинов MCP-Linx"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mcp_linx.types import (
    HealthStatus,
    PluginConfig,
)

if TYPE_CHECKING:
    from mcp_linx.adapters.base import BaseAdapter
    from mcp_linx.multihost import HostRegistry


@dataclass
class PluginTool:
    """Описание MCP tool, предоставляемого плагином"""

    name: str
    description: str
    execute: Any = None


class DiagnosticPlugin(ABC):
    """Базовый интерфейс плагина диагностики"""

    # Уникальный идентификатор плагина
    id: str = ""
    # Отображаемое имя (например, "Linux Host")
    name: str = ""
    # Описание для MCP tool description
    description: str = ""
    # Версия плагина
    version: str = "1.0.0"

    # Список инструментов, предоставляемых плагином
    tools: list[PluginTool] = []

    # Multi-host: реестр удалённых хостов (инжектится agent_loop'ом при setup).
    # None => плагин работает только со своим primary-адаптером.
    hosts: HostRegistry | None = None

    # Primary-адаптер плагина; устанавливается конкретной реализацией в initialize().
    _adapter: BaseAdapter | None = None

    @abstractmethod
    async def initialize(self, config: PluginConfig) -> None:
        """Инициализация плагина (подключение к SSH, API, проверка доступности)"""
        ...

    def _resolve_adapter(self, host: str | None = None) -> BaseAdapter:
        """Адаптер для команды: удалённый хост по имени или primary.

        Args:
            host: имя хоста из секции `hosts:` конфига; None — primary адаптер.

        Raises:
            RuntimeError: плагин не инициализирован (host не задан).
            KeyError: host задан, но не описан в `hosts:` конфига.
        """
        if host:
            if self.hosts is None:
                raise RuntimeError(
                    f"Multi-host not configured: host '{host}' requested, "
                    "but no `hosts:` section in settings.yaml"
                )
            return self.hosts.get_adapter(host)
        if self._adapter is None:
            raise RuntimeError("Plugin not initialized")
        return self._adapter

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Проверка, может ли плагин работать в текущей среде"""
        ...

    @abstractmethod
    async def destroy(self) -> None:
        """Очистка ресурсов (закрытие соединений, туннелей)"""
        ...

    def get_tools(self) -> list[PluginTool]:
        """Возвращает список инструментов плагина"""
        return self.tools
