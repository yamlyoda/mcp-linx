"""Пул SSH-соединений (multi-host поддержка).

Соединения переиспользуются между вызовами инструментов (ключ — host:port:user),
с keepalive и автоматическим переподключением при разрыве. Пул живёт до
shutdown сервера и закрывается один раз.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import socketserver
import threading
import time
from contextlib import suppress
from typing import Any

import paramiko

from mcp_linx.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)


class SSHConnectionPool:
    """Пул paramiko-клиентов, переиспользуемых между вызовами инструментов."""

    def __init__(self, keepalive_seconds: int = 30, connect_timeout: int = 10) -> None:
        self._keepalive = keepalive_seconds
        self._connect_timeout = connect_timeout
        self._clients: dict[tuple[str, int, str | None], paramiko.SSHClient] = {}
        # Bastion-клиенты для jump-хостов (E3): закрываются вместе с целевым.
        self._jump_clients: dict[tuple[str, int, str | None], paramiko.SSHClient] = {}
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
        """Новое SSH-соединение (политики host key — как в SSHAdapter).

        E3: если задан `jump_host`, соединение до цели открывается через
        бастион — `direct-tcpip` канал передаётся в `connect(sock=...)`.
        """
        jump_host = config.get("jump_host")
        sock: paramiko.Channel | None = None

        if jump_host:
            jump_client = self._new_client(self._jump_config(config, str(jump_host)))
            self._jump_clients[self._key(config)] = jump_client
            sock = self._open_jump_channel(jump_client, config)

        return self._new_client(config, sock=sock)

    @staticmethod
    def _jump_config(config: dict[str, Any], jump_host: str) -> dict[str, Any]:
        """Конфиг бастиона из ключей `jump_*` (E3).

        Политика host key и known_hosts берутся из общего конфига хоста: бастион
        проверяется теми же правилами, что и цель (дефолт — reject).
        """
        return {
            "host": jump_host,
            "port": config.get("jump_port", 22),
            "username": config.get("jump_username"),
            "key_file": config.get("jump_key_file"),
            "password": config.get("jump_password"),
            "host_key_policy": config.get("host_key_policy", "reject"),
            "known_hosts": config.get("known_hosts"),
        }

    def _open_jump_channel(
        self, jump_client: paramiko.SSHClient, config: dict[str, Any]
    ) -> paramiko.Channel:
        """Открыть `direct-tcpip` канал через бастион до цели (E3).

        Raises:
            RuntimeError: транспорт бастиона недоступен.
        """
        transport = jump_client.get_transport()
        if transport is None:
            raise RuntimeError("Jump host transport is not available")
        target = (str(config.get("host", "localhost")), int(config.get("port", 22)))
        # source-адрес — от имени бастиона; 0 = любой локальный порт
        return transport.open_channel("direct-tcpip", target, ("127.0.0.1", 0))

    def _new_client(
        self, config: dict[str, Any], sock: paramiko.Channel | None = None
    ) -> paramiko.SSHClient:
        """Клиент с host-key policy, known_hosts и параметрами подключения."""
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
        if sock is not None:
            # E3: подключение через уже открытый канал бастиона
            connect_kwargs["sock"] = sock

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
            # E3: бастионы закрываем вместе с целевыми соединениями
            for jump_client in self._jump_clients.values():
                with suppress(Exception):
                    jump_client.close()
            self._clients.clear()
            self._jump_clients.clear()

    def drop(self, config: dict[str, Any]) -> None:
        """Выбросить соединение из пула (E1): следующий `get()` создаст новое."""
        key = self._key(config)
        with self._lock:
            client = self._clients.pop(key, None)
            jump_client = self._jump_clients.pop(key, None)
        if client is not None:
            with suppress(Exception):  # best-effort закрытие
                client.close()
        if jump_client is not None:
            with suppress(Exception):
                jump_client.close()


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


# Ошибки уровня соединения, при которых имеет смысл переподключиться (E1).
_RETRYABLE_SSH_ERRORS = (paramiko.SSHException, EOFError, OSError, ConnectionError)


def exec_command_with_retry(
    pool: SSHConnectionPool,
    config: dict[str, Any],
    command: str,
    timeout: int,
    attempts: int = 2,
    backoff_seconds: float = 0.5,
) -> dict[str, Any]:
    """Выполнить команду, переподключаясь при обрыве соединения (E1).

    Повтор только на ошибках уровня соединения; ошибки самой команды
    (ненулевой код возврата) не ретраятся, так как возвращаются как результат.

    Args:
        pool: пул соединений.
        config: SSH-конфиг хоста (ключ — host:port:user).
        command: команда (уже прошла `SecurityGuard.validate_command`).
        timeout: таймаут команды в секундах.
        attempts: всего попыток (1 = без повторов).
        backoff_seconds: базовая пауза; растёт линейно (×номер попытки).

    Raises:
        Exception: последняя ошибка соединения, если все попытки исчерпаны.
    """
    attempts = max(1, int(attempts))
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        client = pool.get(config)
        try:
            return exec_command_sync(client, command, timeout)
        except _RETRYABLE_SSH_ERRORS as e:
            last_error = e
            pool.drop(config)  # соединение признано мёртвым — выбросить
            if attempt < attempts:
                time.sleep(backoff_seconds * attempt)

    raise last_error if last_error is not None else RuntimeError("retry loop did not run")


def retry_params(config: dict[str, Any]) -> tuple[int, float]:
    """Параметры retry из конфига хоста/плагина: (attempts, backoff_seconds).

    Дефолт — 2 попытки (одно переподключение) и 0.5 с базовой паузой.
    `retry_attempts: 1` полностью отключает повторы.
    """
    return (
        max(1, int(config.get("retry_attempts", 2))),
        max(0.0, float(config.get("retry_backoff_seconds", 0.5))),
    )


def _relay_bidirectional(local: socket.socket, channel: paramiko.Channel) -> None:
    """Двунаправленная перекачка байт между локальным сокетом и SSH-каналом."""
    done = threading.Event()

    def pump(src: Any, dst: Any) -> None:
        try:
            while True:
                data = src.recv(4096)
                if not data:
                    break
                dst.sendall(data)
        except Exception:  # noqa: S110  # соединение закрылось — это нормально  # nosec B110
            pass
        finally:
            with suppress(Exception):
                dst.shutdown(socket.SHUT_WR)
            done.set()

    threads = [
        threading.Thread(target=pump, args=(local, channel), daemon=True),
        threading.Thread(target=pump, args=(channel, local), daemon=True),
    ]
    for thread in threads:
        thread.start()
    done.wait()


class SSHTunnel:
    """Локальный форвард порта через SSH (paramiko `direct-tcpip`) — E2.

    Открывает `local_host:local_port` и проксирует соединения на
    `remote_host:remote_port` с точки зрения SSH-сервера. Типичное применение —
    подключение к PostgreSQL, доступному только с удалённого хоста.

    Жизненный цикл: `start()` → `local_address` → `stop()`. Поток сервера
    демонический, `stop()` джойнит его с таймаутом.
    """

    def __init__(
        self,
        client: paramiko.SSHClient,
        remote_host: str,
        remote_port: int,
        local_host: str = "127.0.0.1",
        local_port: int = 0,
    ) -> None:
        self._client = client
        self._remote_host = remote_host
        self._remote_port = int(remote_port)
        self._local_host = local_host
        self._local_port = int(local_port)
        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Открыть локальный listener и начать проксирование.

        Raises:
            RuntimeError: SSH-транспорт недоступен (соединение не установлено).
        """
        transport = self._client.get_transport()
        if transport is None:
            raise RuntimeError("SSH transport is not available; connect first")

        remote = (self._remote_host, self._remote_port)

        class _Handler(socketserver.BaseRequestHandler):
            def handle(inner_self) -> None:  # noqa: N805  # имя задано базовым классом
                sock: socket.socket = inner_self.request
                try:
                    channel = transport.open_channel("direct-tcpip", remote, sock.getpeername())
                except Exception:
                    with suppress(Exception):
                        sock.close()
                    return
                # paramiko.Channel совместим с recv/sendall/shutdown, нужными для relay
                try:
                    _relay_bidirectional(sock, channel)
                finally:
                    with suppress(Exception):
                        channel.close()
                    with suppress(Exception):
                        sock.close()

        server = socketserver.ThreadingTCPServer(
            (self._local_host, self._local_port), _Handler, bind_and_activate=True
        )
        server.daemon_threads = True
        server.allow_reuse_address = True
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        logger.info(
            f"SSH tunnel started: {self.local_address[0]}:{self.local_address[1]} "
            f"-> {self._remote_host}:{self._remote_port}"
        )

    def stop(self) -> None:
        """Остановить listener и освободить порт (идемпотентно)."""
        if self._server is not None:
            with suppress(Exception):
                self._server.shutdown()
            with suppress(Exception):
                self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    @property
    def local_address(self) -> tuple[str, int]:
        """Фактический адрес listener (порт известен только после `start()`)."""
        if self._server is None:
            raise RuntimeError("Tunnel not started")
        host, port = self._server.server_address[:2]
        return str(host), int(port)


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
