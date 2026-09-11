"""Базовые классы для плагинов MCP-Linx"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from mcp_linx.types import (
    HealthStatus,
    PluginConfig,
)


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

    @abstractmethod
    async def initialize(self, config: PluginConfig) -> None:
        """Инициализация плагина (подключение к SSH, API, проверка доступности)"""
        ...

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
