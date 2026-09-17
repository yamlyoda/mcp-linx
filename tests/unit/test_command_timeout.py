"""A9: `security.command_timeout_seconds` — реальный дефолт таймаутов команд плагинов.

Проверяем полный путь: конфиг → `SecurityGuard.command_timeout` → `_run*` плагина →
`adapter.execute_command(command, timeout)`, а также приоритет явного per-tool
таймаута над значением из конфига.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest


class _RecordingAdapter:
    """Фейковый адаптер: запоминает (command, timeout) каждого вызова."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int | None]] = []

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def ping(self) -> bool:
        return True

    async def execute_command(self, command: str, timeout: int | None = None) -> dict[str, Any]:
        self.calls.append((command, timeout))
        return {"stdout": "ok", "stderr": "", "returncode": 0, "command": command}


async def _plugin_with_recording_adapter(module: str, class_name: str, timeout_cfg: int = 42):
    """Плагин из `module`, инициализированный с `command_timeout_seconds=timeout_cfg`."""
    plugin_cls = getattr(importlib.import_module(f"mcp_linx.plugins.{module}"), class_name)
    plugin = plugin_cls()
    await plugin.initialize({"security": {"command_timeout_seconds": timeout_cfg}})
    adapter = _RecordingAdapter()
    plugin._adapter = adapter
    return plugin, adapter


# (модуль, класс, метод `_run*`, допустимая read-only команда)
_PLUGIN_RUNS = [
    ("linux", "LinuxPlugin", "_run_command", "uptime"),
    ("nginx", "NginxPlugin", "_run_command", "nginx -t 2>&1"),
    ("systemd", "SystemdPlugin", "_run", "systemctl is-active nginx"),
    ("kubernetes", "KubernetesPlugin", "_run", "kubectl get pods"),
    ("netdiag", "NetdiagPlugin", "_run_privileged", "timeout 1 true"),
    ("redis", "RedisPlugin", "_run_redis_cli", "PING"),
]


class TestConfigTimeoutAsDefault:
    @pytest.mark.parametrize("module,class_name,method,command", _PLUGIN_RUNS)
    @pytest.mark.asyncio
    async def test_plugin_run_uses_config_timeout(self, module, class_name, method, command):
        plugin, adapter = await _plugin_with_recording_adapter(module, class_name)

        result = await getattr(plugin, method)(command)

        assert len(adapter.calls) == 1
        # 42 из конфига, а не прежний хардкод сигнатуры (15/20/30)
        assert adapter.calls[0][1] == 42
        assert result["returncode"] == 0

    @pytest.mark.parametrize("module,class_name,method,command", _PLUGIN_RUNS)
    @pytest.mark.asyncio
    async def test_explicit_timeout_wins(self, module, class_name, method, command):
        plugin, adapter = await _plugin_with_recording_adapter(module, class_name)

        await getattr(plugin, method)(command, timeout=7)

        assert len(adapter.calls) == 1
        assert adapter.calls[0][1] == 7

    @pytest.mark.asyncio
    async def test_tool_without_explicit_timeout_uses_config(self):
        """`linux_disk` таймаут не передаёт → все его команды идут с конфиг-значением."""
        from mcp_linx.plugins.linux.tools import linux_disk

        plugin, adapter = await _plugin_with_recording_adapter("linux", "LinuxPlugin")

        result = await linux_disk(plugin, {})

        assert adapter.calls
        assert {timeout for _, timeout in adapter.calls} == {42}
        assert result.data["disk_usage"] == "ok"


class TestSecurityGuardTimeout:
    def test_default_and_configured(self):
        from mcp_linx.security import SecurityGuard

        assert SecurityGuard({}).command_timeout == 30  # дефолт, как в settings.yaml
        assert SecurityGuard({"command_timeout_seconds": 5}).command_timeout == 5

    def test_requires_initialized_plugin(self):
        from mcp_linx.plugins.linux import LinuxPlugin

        with pytest.raises(RuntimeError, match="not initialized"):
            _ = LinuxPlugin().command_timeout
