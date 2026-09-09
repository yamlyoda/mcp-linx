"""Агентный цикл как плагин.

Позволяет заменять логику работы агента через конфигурацию.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from fastmcp import FastMCP

from mcp_linx.harness.plugin_manager import PluginManager

logger = logging.getLogger(__name__)


class AgentLoop(ABC):
    """Базовый класс агентного цикла.

    Агентный цикл определяет:
    - Как инициализировать плагины
    - Как регистрировать инструменты
    - Как обрабатывать вызовы
    - Как управлять жизненным циклом
    """

    @abstractmethod
    async def setup(self, mcp: FastMCP, plugin_manager: PluginManager, config: dict[str, Any]) -> None:
        """Настройка MCP сервера перед запуском."""
        ...

    @abstractmethod
    async def run(self, mcp: FastMCP, plugin_manager: PluginManager, config: dict[str, Any]) -> None:
        """Запуск основного цикла обработки."""
        ...

    @abstractmethod
    async def shutdown(self, mcp: FastMCP, plugin_manager: PluginManager) -> None:
        """Корректное завершение работы."""
        ...


class DefaultAgentLoop(AgentLoop):
    """Стандартный агентный цикл.

    Регистрирует все инструменты плагинов в MCP сервере
    и запускает стандартный цикл обработки.
    """

    def __init__(self):
        self._context_aggregator = None

    async def setup(self, mcp: FastMCP, plugin_manager: PluginManager, config: dict[str, Any]) -> None:
        """Настройка MCP сервера."""
        from mcp_linx.context_aggregator import ContextAggregator

        self._context_aggregator = ContextAggregator()

        # Инициализация плагинов
        await plugin_manager.initialize_all()

        # Регистрация инструментов
        self._register_tools(mcp, plugin_manager)

        # Регистрация системных инструментов
        self._register_system_tools(mcp, plugin_manager)

        logger.info("MCP server setup complete")

    async def run(self, mcp: FastMCP, plugin_manager: PluginManager, config: dict[str, Any]) -> None:
        """Запуск MCP сервера."""
        logger.info("Starting MCP server...")
        await mcp.run_async()

    async def shutdown(self, mcp: FastMCP, plugin_manager: PluginManager) -> None:
        """Завершение работы."""
        logger.info("Shutting down...")
        await plugin_manager.destroy_all()

    def _register_tools(self, mcp: FastMCP, plugin_manager: PluginManager) -> None:
        """Регистрация инструментов плагинов."""
        tools = plugin_manager.get_tools()

        for tool in tools:
            plugin_id = tool["plugin_id"]
            plugin = plugin_manager.get_plugin(plugin_id)

            if not plugin:
                logger.warning(f"Plugin not found for tool {tool['name']}: {plugin_id}")
                continue

            # Создаём обработчик
            handler = self._make_handler(plugin, tool["name"], tool["execute"])

            # Регистрация в MCP
            mcp.tool(name=tool["name"], description=tool["description"])(handler)

        logger.info(f"Registered {len(tools)} tools")

    def _make_handler(self, plugin, tool_name: str, execute_func):
        """Создание обработчика инструмента."""
        context_aggregator = self._context_aggregator

        async def handler(params: dict[str, Any] | None = None) -> dict[str, Any]:
            params = params or {}

            try:
                result = await execute_func(plugin, params)

                # Добавляем метаданные
                result_dict = result.to_dict() if hasattr(result, "to_dict") else result
                result_dict["metadata"] = result_dict.get("metadata", {})
                result_dict["metadata"]["plugin"] = plugin.id
                result_dict["metadata"]["tool"] = tool_name

                # Обновляем контекст
                if hasattr(result, "status") and plugin:
                    from mcp_linx.types import ComponentState, Status
                    import asyncio

                    component_state = ComponentState(
                        plugin_id=plugin.id,
                        status=result.status if hasattr(result, "status") else Status.UNKNOWN,
                        last_checked=str(asyncio.get_event_loop().time()),
                        issues=result.suggestions if hasattr(result, "suggestions") else [],
                    )
                    context_aggregator.add_component(component_state)

                return result_dict
            except Exception as e:
                logger.error(f"Tool {tool_name} failed: {e}")
                return {
                    "status": "error",
                    "error_message": str(e),
                    "metadata": {"plugin": plugin.id, "tool": tool_name},
                }

        return handler

    def _register_system_tools(self, mcp: FastMCP, plugin_manager: PluginManager) -> None:
        """Регистрация системных инструментов."""
        context_aggregator = self._context_aggregator

        @mcp.tool(name="get_diagnostic_context", description="Получить полный диагностический контекст со всеми компонентами и корреляциями")
        async def get_diagnostic_context() -> dict[str, Any]:
            context = context_aggregator.build_context()
            return {
                "timestamp": context.timestamp,
                "host_id": context.host_id,
                "components": [
                    {
                        "plugin_id": c.plugin_id,
                        "status": c.status.value,
                        "last_checked": c.last_checked,
                        "metrics": c.metrics,
                        "issues": c.issues or [],
                    }
                    for c in context.components
                ],
                "correlations": [
                    {
                        "type": c.type,
                        "source": c.source,
                        "related": c.related,
                        "evidence": c.evidence,
                    }
                    for c in (context.correlations or [])
                ],
            }

        @mcp.tool(name="get_summary", description="Получить сводку по статусам всех компонентов")
        async def get_summary() -> dict[str, Any]:
            return context_aggregator.get_summary()

        @mcp.tool(name="system_health_check", description="Провести health check всех плагинов")
        async def system_health_check() -> dict[str, Any]:
            results = await plugin_manager.health_check_all()
            return {
                "status": "healthy" if all(r.status.value == "healthy" for r in results.values()) else "degraded",
                "results": {
                    k: {"status": r.status.value, "message": r.message}
                    for k, r in results.items()
                },
            }

        logger.info("Registered system tools")


class StreamingAgentLoop(DefaultAgentLoop):
    """Потоковый агентный цикл.

    Расширяет стандартный цикл поддержкой потоковой передачи данных.
    Полезен для длительных операций (логи, мониторинг).
    """

    async def run(self, mcp: FastMCP, plugin_manager: PluginManager, config: dict[str, Any]) -> None:
        """Запуск с поддержкой потоковой передачи."""
        logger.info("Starting streaming MCP server...")
        # В будущем можно добавить SSE или WebSocket транспорт
        await mcp.run_async()

    async def shutdown(self, mcp: FastMCP, plugin_manager: PluginManager) -> None:
        """Завершение работы."""
        logger.info("Shutting down...")
        await plugin_manager.destroy_all()
