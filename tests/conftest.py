"""Фикстуры для тестов MCP-Linx"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import pytest_asyncio

from mcp_linx.types import PluginConfig
from mcp_linx.security import SecurityGuard
from mcp_linx.context_aggregator import ContextAggregator
from mcp_linx.plugins.base import DiagnosticPlugin, PluginTool


# Базовый конфиг для тестов
TEST_CONFIG: dict[str, Any] = {
    "security": {
        "readonly": True,
        "max_command_output_size": 5000,
        "max_log_lines": 100,
        "command_timeout_seconds": 10,
    },
    "plugins": {
        "enabled": ["linux", "nginx", "docker", "postgres"],
        "linux": {
            "ssh": {"host": None},
            "max_command_output_size": 5000,
            "max_log_lines": 100,
        },
        "nginx": {
            "ssh": {"host": None},
            "log_path": "/var/log/nginx",
            "access_log": "access.log",
            "error_log": "error.log",
        },
        "docker": {
            "host": "unix:///var/run/docker.sock",
            "timeout_seconds": 10,
        },
        "postgres": {
            "host": "localhost",
            "port": 5432,
            "database": "testdb",
            "user": "testuser",
            "password": "testpass",
        },
    },
}


@pytest.fixture
def security_guard() -> SecurityGuard:
    """Фикстура SecurityGuard для тестов"""
    return SecurityGuard(TEST_CONFIG.get("security", {}))


@pytest.fixture
def context_aggregator() -> ContextAggregator:
    """Фикстура ContextAggregator для тестов"""
    return ContextAggregator()


@pytest.fixture
def mock_plugin() -> MockPlugin:
    """Фикстура mock плагина для тестов"""
    return MockPlugin(TEST_CONFIG)


class MockPlugin(DiagnosticPlugin):
    """Мок плагин для тестирования"""
    
    id = "mock"
    name = "Mock Plugin"
    description = "Mock plugin for testing"
    version = "1.0.0"
    
    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}
        self._initialized = False
        self._health_status = "healthy"
        self._destroyed = False
    
    async def initialize(self, config: PluginConfig) -> None:
        self._initialized = True
    
    async def health_check(self) -> Any:
        from mcp_linx.types import HealthStatus, Status
        status = Status.HEALTHY if self._health_status == "healthy" else Status.ERROR
        return HealthStatus(status, f"Health: {self._health_status}")
    
    async def destroy(self) -> None:
        self._destroyed = True
    
    def get_tools(self) -> list[PluginTool]:
        return [
            PluginTool("mock_tool", "Mock tool for testing", self.mock_execute),
        ]
    
    async def mock_execute(self, params: dict[str, Any]) -> Any:
        return {
            "status": "ok",
            "data": {"message": "mock response", "params": params},
        }
