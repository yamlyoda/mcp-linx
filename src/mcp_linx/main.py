"""MCP-сервер MCP-Linx — главная точка входа"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import yaml
from fastmcp import FastMCP
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp_linx.plugin_manager import PluginManager, register_plugin
from mcp_linx.plugins.linux import LinuxPlugin
from mcp_linx.plugins.nginx import NginxPlugin
from mcp_linx.plugins.docker import DockerPlugin
from mcp_linx.plugins.postgres import PostgresPlugin
from mcp_linx.types import ToolResult
from mcp_linx.security import SecurityGuard
from mcp_linx.context_aggregator import ContextAggregator

# Регистрация плагинов
register_plugin(LinuxPlugin)
register_plugin(NginxPlugin)
register_plugin(DockerPlugin)
register_plugin(PostgresPlugin)

# Конфигурация через переменные окружения
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
    
    mcp_server_name: str = "mcp-linx"
    mcp_server_version: str = "1.0.0"
    config_path: str = "config/settings.yaml"
    plugins: str = "linux,nginx,docker,postgres"
    log_level: str = "INFO"


settings = Settings()

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("mcp_linx")


def load_config(path: str) -> dict[str, Any]:
    """Загрузить YAML-конфигурацию"""
    config_file = Path(path)
    if config_file.exists():
        with open(config_file, "r") as f:
            return yaml.safe_load(f) or {}
    logger.warning(f"Config file not found: {path}, using defaults")
    return {}


async def start_server():
    """Запустить MCP сервер"""
    # Загрузка конфигурации
    config = load_config(settings.config_path)
    
    # Настройка security guard
    security_config = config.get("security", {})
    security = SecurityGuard(security_config)
    
    # Инициализация plugin manager
    plugin_manager = PluginManager(config)
    plugin_manager.load_plugins()
    
    # Инициализация контекстного агрегатора
    context_aggregator = ContextAggregator()
    
    # Создание FastMCP сервера
    mcp = FastMCP(
        settings.mcp_server_name,
        version=settings.mcp_server_version,
    )
    
    # Регистрация всех инструментов плагинов
    _register_tools(mcp, plugin_manager, security, context_aggregator, config)
    
    # Запуск health check при старте
    try:
        await plugin_manager.initialize_all()
        health = await plugin_manager.health_check_all()
        logger.info(f"All plugins health check: {health}")
    except Exception as e:
        logger.error(f"Failed to initialize plugins: {e}")
        await plugin_manager.destroy_all()
        raise
    
    # Системные инструменты
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
    
    # Запуск сервера
    await mcp.run_async()


def _register_tools(
    mcp: FastMCP,
    plugin_manager: PluginManager,
    security: SecurityGuard,
    context_aggregator: ContextAggregator,
    config: dict[str, Any],
) -> None:
    """Зарегистрировать все tools в MCP сервере"""
    
    tools = plugin_manager.get_tools()
    
    for tool in tools:
        plugin_id = tool["plugin_id"]
        plugin = plugin_manager.get_plugin(plugin_id)
        
        if not plugin:
            logger.warning(f"Plugin not found for tool {tool['name']}: {plugin_id}")
            continue
        
        # Обертываем execute для добавления контекста и безопасности
        def make_handler(
            plugin: DiagnosticPlugin,
            tool_name: str,
            execute_func,
            security: SecurityGuard,
            context_aggregator: ContextAggregator,
        ):
            async def handler(params: dict[str, Any] | None = None) -> dict[str, Any]:
                params = params or {}
                
                # Валидация и выполнение
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
                        component_state = ComponentState(
                            plugin_id=plugin.id,
                            status=result.status if hasattr(result, "status") else Status.UNKNOWN,
                            last_checked=asyncio.get_event_loop().time(),
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
        
        handler = make_handler(
            plugin,
            tool["name"],
            tool["execute"],
            security,
            context_aggregator,
        )
        
        # Регистрация в MCP
        mcp.tool(
            name=tool["name"],
            description=tool["description"],
        )(handler)


async def main():
    """Точка входа для запуска сервера"""
    await start_server()


if __name__ == "__main__":
    asyncio.run(main())
