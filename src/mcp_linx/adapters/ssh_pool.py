"""Пул SSH-соединений (multi-host поддержка).

Соединения переиспользуются между вызовами инструментов (ключ — host:port:user),
с keepalive и автоматическим переподключением при разрыве. Пул живёт до
shutdown сервера и закрывается один раз.
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import suppress
from typing import Any

import paramiko

from mcp_linx.adapters.base import BaseAdapter


class SSHConnectionPool:
    """Пул paramiko-клиентов, переиспользуемых между вызовами инструментов."""

    def __init__(self, keepalive_seconds: int = 30, connect_timeout: int = 10) -> None:
        self._keepalive = keepalive_seconds
        self._connect_timeout = connect_timeout
        self._clients: dict[tuple[str, int, str | None], paramiko.SSHClient] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(config: dict[str, Any]) -> tuple[str, int, str | None]:
        hostname = str(config.get("host", "localhost"))
        port = int(config.get("port", 22))
        username = config.get("username") or None
        return hostname, port, username

    def get(self, config: dict[str, Any]) -> paramiko.SSHClient:
        """Вернуть живое соединение или установить новое (thread-safe)."""
        key = self._key(config)
        with self._lock:
            client = self._clients.get(key)
            if client is not None and self._is_alive(client):
                return client
            if client is not None:
                with suppress(Exception):  # мёртвый клиент, не критично
                    client.close()
                del self._clients[key]

        client = self._connect(config)
        with self._lock:
            self._clients[key] = client
        return client

    @staticmethod
    def _is_alive(client: paramiko.SSHClient) -> bool:
        transport = client.get_transport()
        return transport is not None and transport.is_active()

    def _connect(self, config: dict[str, Any]) -> paramiko.SSHClient:
        """Новое SSH-соединение (политики host key — как в SSHAdapter)."""
        client = paramiko.SSHClient()

        policy = str(config.get("host_key_policy", "reject")).lower()
        if policy == "auto_add":
            # opt-in через конфиг; осознанно ослабленная проверка, дефолт — reject (anti-MITM)
            client.set_missing_host_key_policy(
                paramiko.AutoAddPolicy()  # nosec B507
            )
        elif policy == "warning":
            # opt-in через конфиг; предупреждение, но подключает
            client.set_missing_host_key_policy(
                paramiko.WarningPolicy()  # nosec B507
            )
        else:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())

        try:
            known_hosts = config.get("known_hosts")
            if known_hosts:
                client.load_host_keys(str(known_hosts))
            else:
                client.load_system_host_keys()
        except Exception:
            pass  # known_hosts опциональны  # nosec B110

        connect_kwargs: dict[str, Any] = {
            "hostname": str(config.get("host", "localhost")),
            "port": int(config.get("port", 22)),
            "timeout": self._connect_timeout,
        }
        if config.get("username"):
            connect_kwargs["username"] = config["username"]
        if config.get("key_file"):
            connect_kwargs["key_filename"] = str(config["key_file"])
        elif config.get("password"):
            connect_kwargs["password"] = config["password"]

        client.connect(**connect_kwargs)

        transport = client.get_transport()
        if transport is not None and self._keepalive > 0:
            transport.set_keepalive(self._keepalive)
        return client

    def close_all(self) -> None:
        """Закрыть все соединения (вызывается при shutdown сервера)."""
        with self._lock:
            for client in self._clients.values():
                with suppress(Exception):  # best-effort закрытие
                    client.close()
            self._clients.clear()


def exec_command_sync(client: paramiko.SSHClient, command: str, timeout: int) -> dict[str, Any]:
    """Синхронное выполнение команды через paramiko (общее для SSH-адаптеров)."""
    stdin, stdout, stderr = client.exec_command(
        command,  # команда прошла SecurityGuard.validate_command (allowlist + readonly)  # nosec B601
        timeout=timeout,
    )
    exit_status = stdout.channel.recv_exit_status()
    return {
        "stdout": stdout.read().decode("utf-8", errors="replace"),
        "stderr": stderr.read().decode("utf-8", errors="replace"),
        "returncode": exit_status,
        "command": command,
    }


class RemoteHostAdapter(BaseAdapter):
    """Адаптер выполнения команд на удалённом хосте через пул SSH.

    Создаётся HostRegistry по конфигу одного хоста из секции `hosts:`.
    """

    def __init__(self, pool: SSHConnectionPool, host_config: dict[str, Any]):
        super().__init__(host_config)
        self._pool = pool

    async def connect(self) -> None:
        """Прогреть соединение (лениво создаётся и при первом execute_command)."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._pool.get, self.config)

    async def disconnect(self) -> None:
        """Соединения живут в пуле; закрываются через pool.close_all() при shutdown."""

    async def ping(self) -> bool:
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
        loop = asyncio.get_event_loop()
        client = await loop.run_in_executor(None, self._pool.get, self.config)
        return await loop.run_in_executor(None, exec_command_sync, client, command, timeout)
