#!/usr/bin/env python3
"""Скрипт для запуска MCP Inspector с mcp-linx сервером"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Добавляем src в путь
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mcp_linx.main import start_server


async def run_with_inspector():
    """Запуск сервера в режиме совместимости с MCP Inspector"""
    import os
    
    # MCP Inspector ожидает сервер на stdio
    # FastMCP по умолчанию работает через stdio
    
    print("Starting mcp-linx server for MCP Inspector...", file=sys.stderr)
    print("""
    MCP Inspector доступен по команде:
    
        npx @modelcontextprotocol/inspector node --server-command "python -m mcp_linx.main"
    
    Или для Python:
    
        uvx mcp-inspector python -m mcp_linx.main
    
    После запуска откройте:
        http://localhost:6274  (или порт, указанный в выводе)
    """, file=sys.stderr)
    
    # Запускаем сервер
    await start_server()


def main():
    parser = argparse.ArgumentParser(description="MCP-Linx Server — диагностика Linux-инфраструктуры")
    parser.add_argument(
        "--inspector",
        action="store_true",
        help="Режим совместимости с MCP Inspector (без изменений)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/settings.yaml",
        help="Путь к YAML конфигурации",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Диагностический режим (подробное логирование)",
    )
    
    args = parser.parse_args()
    
    if args.debug:
        import logging
        logging.getLogger("mcp_linx").setLevel(logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Установка пути к конфигурации
    import os
    os.environ["MCP_LINX_CONFIG"] = args.config
    
    asyncio.run(run_with_inspector())


if __name__ == "__main__":
    main()
