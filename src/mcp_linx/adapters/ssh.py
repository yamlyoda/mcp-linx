"""SSH адаптер для MCP-Linx (paramiko)"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import paramiko

from mcp_linx.adapters.base import BaseAdapter
from mcp_linx.adapters.ssh_pool import (
    SSHConnectionPool,
    exec_command_with_retry,
    retry_params,
)


class SSHAdapter(BaseAdapter):
    """Адаптер для выполнения команд через SSH"""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._client: paramiko.SSHClient | None = None
        # Собственный пул: disconnect одного плагина не затрагивает другие.
        self._pool = SSHConnectionPool()

    async def connect(self) -> None:
        """Получить живое соединение через общий SSH-код (в executor)."""
        loop = asyncio.get_running_loop()
        self._client = await loop.run_in_executor(None, self._pool.get, self.config)

    async def disconnect(self) -> None:
        """Закрыть SSH-соединение"""
        await asyncio.get_running_loop().run_in_executor(None, self._pool.close_all)
        self._client = None

    async def _ensure_client(self) -> paramiko.SSHClient:
        """Гарантировать подключение и вернуть клиент (не-Optional)."""
        await self.connect()  # пул проверяет transport и заменяет мёртвое соединение
        if self._client is None:
            raise RuntimeError("SSH client not initialized")
        return self._client

    async def ping(self) -> bool:
        """Проверка SSH-доступности"""
        try:
            result = await self.execute_command("echo OK", timeout=5)
            return bool(result["returncode"] == 0 and result["stdout"].strip() == "OK")
        except Exception:
            return False

    async def execute_command(
        self,
        command: str,
        timeout: int = 30,
    ) -> dict[str, Any]:
        """Выполнить команду через SSH

        Args:
            command: Команда для выполнения
            timeout: Таймаут в секундах

        Returns:
            dict с stdout, stderr, returncode
        """
        await self._ensure_client()
        loop = asyncio.get_running_loop()
        attempts, backoff = retry_params(self.config)
        return await loop.run_in_executor(
            None,
            exec_command_with_retry,
            self._pool,
            self.config,
            command,
            timeout,
            attempts,
            backoff,
        )

    async def execute_and_parse(
        self,
        command: str,
        parser: Callable[[str], Any],
        timeout: int = 30,
    ) -> Any:
        """Выполнить команду и распарсить результат"""
        result = await self.execute_command(command, timeout)
        if result["returncode"] != 0 and not result["stdout"]:
            raise RuntimeError(f"Command failed: {result['stderr']}")
        return parser(result["stdout"])

    @property
    def client(self) -> paramiko.SSHClient | None:
        """Доступ к raw SSH клиенту (для расширенных операций)"""
        return self._client
