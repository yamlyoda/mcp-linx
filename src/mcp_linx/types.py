"""Общие типы данных проекта MCP-Linx"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Status(str, Enum):
    """Статус диагностики"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"
    ERROR = "error"


class ToolResult:
    """Результат выполнения MCP tool"""
    
    def __init__(
        self,
        status: Status = Status.UNKNOWN,
        data: Any = None,
        metadata: dict[str, Any] | None = None,
        suggestions: list[str] | None = None,
        error_message: str | None = None,
    ):
        self.status = status
        self.data = data
        self.metadata = metadata or {}
        self.suggestions = suggestions or []
        self.error_message = error_message
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "data": self.data,
            "metadata": self.metadata,
            "suggestions": self.suggestions,
            "error_message": self.error_message,
        }
    
    @classmethod
    def ok(cls, data: Any, metadata: dict[str, Any] | None = None) -> "ToolResult":
        return cls(status=Status.HEALTHY, data=data, metadata=metadata or {})
    
    @classmethod
    def degraded(
        cls,
        data: Any,
        suggestions: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> "ToolResult":
        return cls(status=Status.DEGRADED, data=data, suggestions=suggestions, metadata=metadata or {})
    
    @classmethod
    def error(cls, error_message: str, metadata: dict[str, Any] | None = None) -> "ToolResult":
        return cls(status=Status.ERROR, error_message=error_message, metadata=metadata or {})


@dataclass
class ComponentState:
    """Состояние компонента для контекстного агрегатора"""
    plugin_id: str
    status: Status
    last_checked: str
    metrics: dict[str, Any] | None = None
    issues: list[str] | None = None


@dataclass
class Correlation:
    """Корреляция между компонентами"""
    type: str  # cascade | root_cause_suspected
    source: str
    related: list[str]
    evidence: str


@dataclass
class DiagnosticContext:
    """Контекст диагностики"""
    timestamp: str
    host_id: str
    components: list[ComponentState]
    correlations: list[Correlation] | None = None


class PluginConfig(dict):
    """Конфигурация плагина — наследуем dict для гибкости"""
    pass


class HealthStatus:
    """Статус health-check плагина"""
    
    def __init__(self, status: Status = Status.UNKNOWN, message: str = ""):
        self.status = status
        self.message = message
    
    def is_healthy(self) -> bool:
        return self.status == Status.HEALTHY
