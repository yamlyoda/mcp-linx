"""Wave 7: `LocalAdapter` — локальное выполнение команд (реальный subprocess).

Покрываем connect/disconnect/ping/execute_command/execute_and_parse: успех,
непустой stderr, ненулевой код возврата, таймаут с kill, очистка пула процессов
и ветки ошибок. Команды короткие и без побочных эффектов.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mcp_linx.adapters.base import BaseAdapter, LocalAdapter


class _Dummy(BaseAdapter):
    """Минимальный адаптер без поддержки команд."""

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def ping(self) -> bool:
        return True


class TestBaseAdapter:
    @pytest.mark.asyncio
    async def test_execute_command_not_supported_by_default(self):
        with pytest.raises(NotImplementedError, match="_Dummy"):
            await _Dummy().execute_command("echo hi")


class TestLocalLifecycle:
    @pytest.mark.asyncio
    async def test_connect_is_noop(self):
        assert await LocalAdapter().connect() is None

    @pytest.mark.asyncio
    async def test_ping_true_on_healthy_host(self):
        assert await LocalAdapter().ping() is True

    @pytest.mark.asyncio
    async def test_ping_false_when_spawn_fails(self, monkeypatch):
        import mcp_linx.adapters.base as mod

        async def boom(*args: Any, **kwargs: Any) -> Any:
            raise OSError("no uname")

        monkeypatch.setattr(mod.asyncio, "create_subprocess_exec", boom)

        assert await LocalAdapter().ping() is False

    @pytest.mark.asyncio
    async def test_disconnect_terminates_tracked_processes(self):
        """disconnect() завершает отслеживаемые процессы и очищает пул."""
        from unittest.mock import AsyncMock, MagicMock

        adapter = LocalAdapter()
        proc = MagicMock()
        proc.wait = AsyncMock()
        adapter._pool.add(proc)

        await adapter.disconnect()

        proc.terminate.assert_called_once()
        proc.wait.assert_awaited_once()
        assert adapter._pool == set()

    @pytest.mark.asyncio
    async def test_disconnect_ignores_terminate_errors(self):
        """best-effort cleanup: ошибка terminate не прерывает disconnect."""
        from unittest.mock import MagicMock

        adapter = LocalAdapter()
        proc = MagicMock()
        proc.terminate.side_effect = ProcessLookupError("already gone")
        adapter._pool.add(proc)

        await adapter.disconnect()

        assert adapter._pool == set()


class TestLocalExecuteCommand:
    @pytest.mark.asyncio
    async def test_success_returns_stdout_returncode_command(self):
        adapter = LocalAdapter()

        result = await adapter.execute_command("printf 'hello'", timeout=10)

        assert result["stdout"] == "hello"
        assert result["returncode"] == 0
        assert result["command"] == "printf 'hello'"
        assert adapter._pool == set()

    @pytest.mark.asyncio
    async def test_stderr_captured_and_nonzero_code(self):
        adapter = LocalAdapter()

        result = await adapter.execute_command("sh -c 'echo oops 1>&2; exit 3'", timeout=10)

        assert result["returncode"] == 3
        assert "oops" in result["stderr"]

    @pytest.mark.asyncio
    async def test_timeout_kills_process_and_reraises(self, monkeypatch):
        """Таймаут: процесс убивается, пул очищается, TimeoutError уходит наверх."""
        import mcp_linx.adapters.base as mod

        class _SlowProc:
            def __init__(self) -> None:
                self.killed = False
                self.returncode = None

            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.sleep(10)
                raise AssertionError("unreachable")

            def kill(self) -> None:
                self.killed = True

            async def wait(self) -> int:
                return 0

        proc = _SlowProc()

        async def spawn(*args: Any, **kwargs: Any) -> Any:
            return proc

        monkeypatch.setattr(mod.asyncio, "create_subprocess_shell", spawn)
        adapter = LocalAdapter()

        with pytest.raises(TimeoutError):
            await adapter.execute_command("sleep 10", timeout=1)

        assert proc.killed is True
        assert adapter._pool == set()

    @pytest.mark.asyncio
    async def test_unexpected_error_discards_process(self, monkeypatch):
        """Ошибка не-Timeout типа: процесс снимается с учёта и исключение уходит наверх."""
        import mcp_linx.adapters.base as mod

        class _BrokenProc:
            returncode = 0

            async def communicate(self) -> tuple[bytes, bytes]:
                raise ValueError("boom")

            def kill(self) -> None: ...

            async def wait(self) -> int:
                return 0

        async def spawn(*args: Any, **kwargs: Any) -> Any:
            return _BrokenProc()

        monkeypatch.setattr(mod.asyncio, "create_subprocess_shell", spawn)
        adapter = LocalAdapter()

        with pytest.raises(ValueError, match="boom"):
            await adapter.execute_command("echo x", timeout=5)

        assert adapter._pool == set()


class TestLocalExecuteAndParse:
    @pytest.mark.asyncio
    async def test_parses_stdout_on_success(self):
        adapter = LocalAdapter()

        parsed = await adapter.execute_and_parse("printf 'a,b'", lambda s: s.split(","), timeout=10)

        assert parsed == ["a", "b"]

    @pytest.mark.asyncio
    async def test_raises_on_nonzero_returncode(self):
        adapter = LocalAdapter()

        with pytest.raises(RuntimeError, match="Command failed"):
            await adapter.execute_and_parse(
                "sh -c 'echo boom 1>&2; exit 2'", lambda s: s, timeout=10
            )
