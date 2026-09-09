"""MCP-сервер MCP-Linx — главная точка входа.

Использует Harness-архитектуру: всё есть плагин.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import yaml
from fastmcp import FastMCP
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp_linx.harness import (
    DefaultAgentLoop,
    discover_plugins,
    PluginManager,
)

# Конфигурация через переменные окружения
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    mcp_server_name: str = "mcp-linx"
    mcp_server_version: str = "1.0.0"
    config_path: str = "config/settings.yaml"
    plugins: str = "linux,nginx,docker,postgres"
    log_level: str = "INFO"
    agent_loop: str = "default"  # default | streaming


settings = Settings()

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("mcp_linx")


def load_config(path: str) -> dict:
    """Загрузить YAML-конфигурацию."""
    config_file = Path(path)
    if config_file.exists():
        with open(config_file, "r") as f:
            return yaml.safe_load(f) or {}
    logger.warning(f"Config file not found: {path}, using defaults")
    return {}


def get_agent_loop(loop_type: str):
    """Получить агентный цикл по типу."""
    loops = {
        "default": DefaultAgentLoop,
    }

    loop_class = loops.get(loop_type, DefaultAgentLoop)
    return loop_class()


async def start_server():
    """Запустить MCP сервер."""
    # Загрузка конфигурации
    config = load_config(settings.config_path)

    # Автообнаружение плагинов (Harness-идеология)
    discovered = discover_plugins()
    logger.info(f"Discovered {discovered} plugins")

    # Инициализация менеджера плагинов
    plugin_manager = PluginManager(config)

    # Загрузка плагинов
    plugin_manager.load_plugins()

    # Создание MCP сервера
    mcp = FastMCP(
        settings.mcp_server_name,
        version=settings.mcp_server_version,
    )

    # Получение агентного цикла из конфига
    agent_loop = get_agent_loop(settings.agent_loop)

    # Настройка сервера
    await agent_loop.setup(mcp, plugin_manager, config)

    # Health check при старте
    try:
        health = await plugin_manager.health_check_all()
        logger.info(f"Health check: {health}")
    except Exception as e:
        logger.error(f"Health check failed: {e}")

    # Запуск сервера
    try:
        await agent_loop.run(mcp, plugin_manager, config)
    finally:
        await agent_loop.shutdown(mcp, plugin_manager)


async def main():
    """Точка входа для запуска сервера."""
    await start_server()


if __name__ == "__main__":
    asyncio.run(main())
