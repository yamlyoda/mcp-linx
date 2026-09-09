"""Песочница как плагин.

Обеспечивает изолированное выполнение команд.
"""

from __future__ import annotations

import asyncio
import logging
import shlex
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class Sandbox(ABC):
    """Базовый класс песочницы.

    Песочница определяет, как выполняются команды:
    - Локально
    - В Docker контейнере
    - На удалённом хосте
    """

    @abstractmethod
    async def execute(self, command: str, timeout: int = 30) -> dict[str, Any]:
        """Выполнить команду в песочнице.

        Args:
            command: Команда для выполнения
            timeout: Таймаут в секундах

        Returns:
            Результат выполнения с stdout, stderr, returncode
        """
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Проверить доступность песочницы.

        Returns:
            True если песочница доступна
        """
        ...


class LocalSandbox(Sandbox):
    """Локальная песочница.

    Выполняет команды на локальной машине.
    """

    async def execute(self, command: str, timeout: int = 30) -> dict[str, Any]:
        """Выполнить команду локально."""
        args = shlex.split(command)

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "returncode": proc.returncode,
                "command": command,
            }
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {
                "stdout": "",
                "stderr": f"Command timed out after {timeout}s",
                "returncode": -1,
                "command": command,
            }

    async def is_available(self) -> bool:
        """Проверить доступность (всегда True для локальной)."""
        return True


class DockerSandbox(Sandbox):
    """Docker песочница.

    Выполняет команды внутри Docker контейнера.
    Полезно для изоляции и безопасности.
    """

    def __init__(self, image: str = "alpine:latest", container_name: str | None = None):
        self._image = image
        self._container_name = container_name or f"mcp-sandbox-{id(self)}"

    async def execute(self, command: str, timeout: int = 30) -> dict[str, Any]:
        """Выполнить команду в Docker контейнере."""
        # Используем docker run для однократного выполнения
        docker_command = (
            f"docker run --rm --network none "
            f"--memory 128m --cpus 0.5 "
            f"{self._image} sh -c {shlex.quote(command)}"
        )

        args = shlex.split(docker_command)

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "returncode": proc.returncode,
                "command": command,
            }
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {
                "stdout": "",
                "stderr": f"Command timed out after {timeout}s",
                "returncode": -1,
                "command": command,
            }

    async def is_available(self) -> bool:
        """Проверить доступность Docker."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            return proc.returncode == 0
        except Exception:
            return False


class RemoteSandbox(Sandbox):
    """Удалённая песочница через SSH.

    Выполняет команды на удалённом хосте.
    """

    def __init__(self, host: str, port: int = 22, username: str | None = None, key_file: str | None = None):
        self._host = host
        self._port = port
        self._username = username
        self._key_file = key_file

    async def execute(self, command: str, timeout: int = 30) -> dict[str, Any]:
        """Выполнить команду на удалённом хосте через SSH."""
        from mcp_linx.adapters.ssh import SSHAdapter

        config = {
            "host": self._host,
            "port": self._port,
        }
        if self._username:
            config["username"] = self._username
        if self._key_file:
            config["key_file"] = self._key_file

        adapter = SSHAdapter(config)
        try:
            await adapter.connect()
            result = await adapter.execute_command(command, timeout)
            return result
        finally:
            await adapter.disconnect()

    async def is_available(self) -> bool:
        """Проверить доступность SSH."""
        from mcp_linx.adapters.ssh import SSHAdapter

        config = {
            "host": self._host,
            "port": self._port,
        }
        if self._username:
            config["username"] = self._username
        if self._key_file:
            config["key_file"] = self._key_file

        adapter = SSHAdapter(config)
        try:
            return await adapter.ping()
        except Exception:
            return False
