"""SSH адаптер для MCP-Linx (paramiko)"""

from __future__ import annotations

import asyncio
from typing import Any

import paramiko

from mcp_linx.adapters.base import BaseAdapter


class SSHAdapter(BaseAdapter):
    """Адаптер для выполнения команд через SSH"""
    
    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._client: paramiko.SSHClient | None = None
        self._host: str | None = None
        self._port: int = 22
        self._username: str | None = None
        self._key_file: str | None = None
        self._password: str | None = None
    
    async def connect(self) -> None:
        """Установить SSH-соединение"""
        loop = asyncio.get_event_loop()
        
        self._client = paramiko.SSHClient()
        
        # Host key policy из конфига (дефолт: reject — защита от MITM).
        # Допустимые значения: reject | warning | auto_add
        policy = str(self.config.get("host_key_policy", "reject")).lower()
        if policy == "auto_add":
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        elif policy == "warning":
            self._client.set_missing_host_key_policy(paramiko.WarningPolicy())
        else:
            self._client.set_missing_host_key_policy(paramiko.RejectPolicy())
        
        # Загрузка known_hosts для проверки ключей хоста
        try:
            known_hosts = self.config.get("known_hosts")
            if known_hosts:
                self._client.load_host_keys(str(known_hosts))
            else:
                self._client.load_system_host_keys()
        except Exception:
            # Отсутствие known_hosts не блокирует подключение,
            # но RejectPolicy отклонит неизвестный хост.
            pass
        
        await loop.run_in_executor(
            None,
            self._connect_sync,
        )
    
    def _connect_sync(self) -> None:
        """Синхронное подключение (run в executor)"""
        config = self.config
        self._host = config.get("host", "localhost")
        self._port = int(config.get("port", 22))
        self._username = config.get("username") or None
        self._key_file = config.get("key_file") or None
        self._password = config.get("password") or None
        
        connect_kwargs: dict[str, Any] = {
            "hostname": self._host,
            "port": self._port,
        }
        
        if self._username:
            connect_kwargs["username"] = self._username
        
        if self._key_file:
            connect_kwargs["key_filename"] = self._key_file
        elif self._password:
            connect_kwargs["password"] = self._password
        
        self._client.connect(**connect_kwargs)
    
    async def disconnect(self) -> None:
        """Закрыть SSH-соединение"""
        if self._client:
            self._client.close()
            self._client = None
    
    async def ping(self) -> bool:
        """Проверка SSH-доступности"""
        if not self._client:
            await self.connect()
        try:
            stdin, stdout, stderr = self._client.exec_command("echo OK", timeout=5)
            return stdout.read().decode().strip() == "OK"
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
        if not self._client:
            await self.connect()
        
        loop = asyncio.get_event_loop()
        
        result = await loop.run_in_executor(
            None,
            lambda: self._execute_command_sync(command, timeout),
        )
        
        return result
    
    def _execute_command_sync(self, command: str, timeout: int) -> dict[str, Any]:
        """Синхронное выполнение команды"""
        if not self._client:
            raise RuntimeError("SSH client not connected")
        
        stdin, stdout, stderr = self._client.exec_command(
            command,
            timeout=timeout,
        )
        
        exit_status = stdout.channel.recv_exit_status()
        
        return {
            "stdout": stdout.read().decode("utf-8", errors="replace"),
            "stderr": stderr.read().decode("utf-8", errors="replace"),
            "returncode": exit_status,
            "command": command,
        }
    
    async def execute_and_parse(
        self,
        command: str,
        parser: callable,
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
