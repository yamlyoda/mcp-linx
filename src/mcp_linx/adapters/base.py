"""Базовый адаптер и адаптеры для MCP-Linx"""

from __future__ import annotations

import asyncio
import shlex
import subprocess
from abc import ABC, abstractmethod
from typing import Any


class BaseAdapter(ABC):
    """Базовый класс адаптера"""
    
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
    
    @abstractmethod
    async def connect(self) -> None:
        """Установить соединение"""
        ...
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Закрыть соединение"""
        ...
    
    @abstractmethod
    async def ping(self) -> bool:
        """Проверка доступности"""
        ...


class LocalAdapter(BaseAdapter):
    """Адаптер для выполнения команд на локальной системе"""
    
    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._pool: set[asyncio.subprocess.Process] = set()
    
    async def connect(self) -> None:
        """Локальный адаптер не требует соединения"""
        pass
    
    async def disconnect(self) -> None:
        """Закрытие всех активных процессов"""
        for proc in self._pool:
            try:
                proc.terminate()
                await proc.wait()
            except Exception:
                pass
        self._pool.clear()
    
    async def ping(self) -> bool:
        """Проверка, что локальная система доступна"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "uname", "-s",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._pool.add(proc)
            stdout, _ = await proc.communicate()
            await proc.wait()
            self._pool.discard(proc)
            return proc.returncode == 0
        except Exception:
            return False
    
    async def execute_command(
        self,
        command: str,
        timeout: int = 30,
    ) -> dict[str, Any]:
        """Выполнить команду на локальной системе
        
        Args:
            command: Команда для выполнения
            timeout: Таймаут в секундах
            
        Returns:
            dict с stdout, stderr, returncode
        """
        # Экранирование аргументов
        args = shlex.split(command)
        
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._pool.add(proc)
        
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
            await proc.wait()
            self._pool.discard(proc)
            
            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "returncode": proc.returncode,
                "command": command,
            }
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            self._pool.discard(proc)
            raise
        except Exception:
            self._pool.discard(proc)
            raise
    
    async def execute_and_parse(
        self,
        command: str,
        parser: callable,
        timeout: int = 30,
    ) -> Any:
        """Выполнить команду и распарсить результат
        
        Args:
            command: Команда для выполнения
            parser: Функция парсинга stdout
            timeout: Таймаут в секундах
        """
        result = await self.execute_command(command, timeout)
        if result["returncode"] != 0:
            raise RuntimeError(f"Command failed: {result['stderr']}")
        return parser(result["stdout"])
