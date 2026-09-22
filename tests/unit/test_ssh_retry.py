"""Wave 10 (E1): retry с backoff и переподключением для SSH-команд.

Проверяем `exec_command_with_retry`, `retry_params` и `SSHConnectionPool.drop`
без сети: пул и `exec_command_sync` подменяются.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import paramiko
import pytest

import mcp_linx.adapters.ssh_pool as sp
from mcp_linx.adapters.ssh_pool import (
    SSHConnectionPool,
    exec_command_with_retry,
    retry_params,
)

CONFIG: dict[str, Any] = {"host": "10.0.0.1", "port": 22, "username": "u"}


def _pool() -> MagicMock:
    pool = MagicMock(spec=SSHConnectionPool)
    pool.get.return_value = MagicMock()
    return pool


class TestRetryParams:
    def test_defaults(self):
        assert retry_params({}) == (2, 0.5)

    def test_custom_values(self):
        assert retry_params({"retry_attempts": 4, "retry_backoff_seconds": 1.5}) == (4, 1.5)

    def test_attempts_never_below_one(self):
        assert retry_params({"retry_attempts": 0})[0] == 1
        assert retry_params({"retry_attempts": -5})[0] == 1

    def test_negative_backoff_clamped_to_zero(self):
        assert retry_params({"retry_backoff_seconds": -1})[1] == 0.0


class TestExecCommandWithRetry:
    def test_success_on_first_attempt_does_not_drop(self, monkeypatch):
        pool = _pool()
        monkeypatch.setattr(sp, "exec_command_sync", lambda c, cmd, t: {"stdout": "ok"})

        result = exec_command_with_retry(pool, CONFIG, "echo ok", 5)

        assert result == {"stdout": "ok"}
        pool.drop.assert_not_called()

    def test_reconnects_and_succeeds_on_second_attempt(self, monkeypatch):
        pool = _pool()
        calls: list[int] = []
        sleeps: list[float] = []

        def flaky(client: Any, command: str, timeout: int) -> dict[str, Any]:
            calls.append(1)
            if len(calls) == 1:
                raise paramiko.SSHException("broken pipe")
            return {"stdout": "recovered"}

        monkeypatch.setattr(sp, "exec_command_sync", flaky)
        monkeypatch.setattr(sp.time, "sleep", sleeps.append)

        result = exec_command_with_retry(
            pool, CONFIG, "uname -a", 5, attempts=2, backoff_seconds=0.5
        )

        assert result["stdout"] == "recovered"
        assert len(calls) == 2
        pool.drop.assert_called_once()
        assert sleeps == [0.5]  # линейный backoff: 0.5 × 1

    def test_raises_last_error_after_all_attempts(self, monkeypatch):
        pool = _pool()
        attempts_made: list[int] = []

        def always_fails(client: Any, command: str, timeout: int) -> dict[str, Any]:
            attempts_made.append(1)
            raise OSError("network down")

        monkeypatch.setattr(sp, "exec_command_sync", always_fails)
        monkeypatch.setattr(sp.time, "sleep", lambda s: None)

        with pytest.raises(OSError, match="network down"):
            exec_command_with_retry(pool, CONFIG, "uptime", 5, attempts=3)

        assert len(attempts_made) == 3
        assert pool.drop.call_count == 3

    def test_retry_attempts_one_disables_repeats(self, monkeypatch):
        pool = _pool()
        attempts_made: list[int] = []

        def fails(client: Any, command: str, timeout: int) -> dict[str, Any]:
            attempts_made.append(1)
            raise EOFError("closed")

        monkeypatch.setattr(sp, "exec_command_sync", fails)

        with pytest.raises(EOFError):
            exec_command_with_retry(pool, CONFIG, "uptime", 5, attempts=1)

        assert len(attempts_made) == 1

    def test_non_connection_error_is_not_retried(self, monkeypatch):
        """Логическая ошибка (например, ошибка парсинга) не должна вызывать reconnect."""
        pool = _pool()

        def bad_config(client: Any, command: str, timeout: int) -> dict[str, Any]:
            raise ValueError("bad command")

        monkeypatch.setattr(sp, "exec_command_sync", bad_config)

        with pytest.raises(ValueError, match="bad command"):
            exec_command_with_retry(pool, CONFIG, "x", 5, attempts=3)

        pool.drop.assert_not_called()

    def test_no_sleep_on_last_attempt(self, monkeypatch):
        pool = _pool()
        sleeps: list[float] = []

        def fails(client: Any, command: str, timeout: int) -> dict[str, Any]:
            raise ConnectionError("reset")

        monkeypatch.setattr(sp, "exec_command_sync", fails)
        monkeypatch.setattr(sp.time, "sleep", sleeps.append)

        with pytest.raises(ConnectionError):
            exec_command_with_retry(pool, CONFIG, "x", 5, attempts=3)

        # пауза только между попытками: attempts - 1
        assert sleeps == [0.5, 1.0]


class TestPoolDrop:
    def test_drop_closes_and_forgets_client(self, monkeypatch):
        pool = SSHConnectionPool()
        client = MagicMock()
        client.get_transport.return_value = MagicMock()
        monkeypatch.setattr(sp.paramiko, "SSHClient", lambda: client)
        pool.get(CONFIG)

        pool.drop(CONFIG)

        client.close.assert_called_once()
        assert pool._clients == {}

    def test_drop_missing_key_is_noop(self):
        pool = SSHConnectionPool()
        pool.drop(CONFIG)  # не должно падать
        assert pool._clients == {}
