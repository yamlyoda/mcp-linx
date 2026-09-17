"""MCP-сервер MCP-Linx — главная точка входа.

Использует Harness-архитектуру: всё есть плагин.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any

import yaml
from fastmcp import FastMCP
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp_linx.harness import (
    AgentLoop,
    DefaultAgentLoop,
    PluginManager,
    StreamingAgentLoop,
    discover_plugins,
)


# Конфигурация через переменные окружения.
# Фактические имена — БЕЗ префикса (MCP_SERVER_NAME, CONFIG_PATH, LOG_LEVEL, ...):
# `LINX_*` сознательно не поддерживаются, см. `.env.example` и README.
# A10 (FIXED 2026-09-17): поле `plugins` удалено — состав плагинов определяет
# только `config/settings.yaml::plugins.enabled` (PluginManager.load_plugins()).
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    mcp_server_name: str = "mcp-linx"
    mcp_server_version: str = "1.0.0"
    config_path: str = "config/settings.yaml"
    log_level: str = "INFO"
    agent_loop: str = "default"  # default | streaming


settings = Settings()

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)

logger = logging.getLogger("mcp_linx")

_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand_env_vars(text: str) -> str:
    """Раскрыть ${VAR} / ${VAR:-default} из os.environ (A4).

    Незаданная переменная без default → ValueError (fail-fast вместо
    молчаливого пустого секрета).
    """

    def _repl(m: re.Match[str]) -> str:
        name, default = m.group(1), m.group(2)
        if name in os.environ:
            return os.environ[name]
        if default is not None:
            return default
        raise ValueError(f"environment variable {name} is not set (no default)")

    return _ENV_VAR_RE.sub(_repl, text)


def load_config(path: str) -> dict[str, Any]:
    """Загрузить YAML-конфигурацию с раскрытием ${VAR} / ${VAR:-default} из env (A4)."""
    config_file = Path(path)
    if config_file.exists():
        with open(config_file) as f:
            raw = f.read()
        try:
            expanded = _expand_env_vars(raw)
        except ValueError as e:
            logger.warning(f"Config env-substitution failed: {e}; using raw content")
            expanded = raw
        result: dict[str, Any] = yaml.safe_load(expanded) or {}
        return result
    logger.warning(f"Config file not found: {path}, using defaults")
    return {}


def get_agent_loop(loop_type: str) -> AgentLoop:
    """Получить агентный цикл по типу."""
    loops: dict[str, type[AgentLoop]] = {
        "default": DefaultAgentLoop,
        "streaming": StreamingAgentLoop,
    }

    loop_class = loops.get(loop_type, DefaultAgentLoop)
    return loop_class()


async def start_server() -> None:
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


async def _main_async() -> None:
    """Асинхронная точка входа: запуск сервера с обработкой SIGTERM/SIGINT."""
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _on_signal(sig: int) -> None:
        logger.info(f"Received signal {signal.Signals(sig).name}, shutting down...")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        with suppress(NotImplementedError):
            # Windows doesn't support add_signal_handler
            loop.add_signal_handler(sig, _on_signal, sig)

    server_task = asyncio.create_task(start_server())
    stop_task = asyncio.create_task(stop_event.wait())
    done, pending = await asyncio.wait(
        {server_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
    )
    if stop_task in done:
        # Сигнал пришёл раньше завершения сервера: отменяем серверную задачу.
        # start_server() выполняет cleanup (destroy_all + close_all) в finally
        # через agent_loop.shutdown().
        server_task.cancel()
        with suppress(asyncio.CancelledError):
            await server_task
    else:
        stop_task.cancel()
        with suppress(asyncio.CancelledError):
            await stop_task
    for task in pending:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def main() -> None:
    """Синхронная точка входа для console script (`mcp-linx`) и `python -m mcp_linx`."""
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
