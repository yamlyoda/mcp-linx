"""Audit logging для MCP-Linx.

Записывает JSON-строки о каждом вызове инструмента:
timestamp, tool, plugin, status, duration_ms, параметры (санитизированные).
Параметры очищаются от секретов (password, token, secret, key) перед записью.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("mcp_linx.audit")

# Ключи, значения которых не должны попадать в аудит-лог
_SENSITIVE_KEYS = {
    "password",
    "passwd",
    "token",
    "api_key",
    "apikey",
    "secret",
    "authorization",
    "cookie",
    "key_file",
    "known_hosts",
    "private_key",
}
_REDACTED = "***REDACTED***"


def sanitize_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """Рекурсивно вычищает секреты из параметров для аудит-лога."""
    if not isinstance(params, dict):
        return {}

    cleaned: dict[str, Any] = {}
    for key, value in params.items():
        lower_key = str(key).lower()

        if any(s in lower_key for s in _SENSITIVE_KEYS):
            cleaned[key] = _REDACTED
        elif isinstance(value, dict):
            cleaned[key] = sanitize_params(value)
        elif isinstance(value, list):
            cleaned[key] = [
                sanitize_params(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            cleaned[key] = value
    return cleaned


class AuditLogger:
    """Пишет JSON-логи вызовов инструментов в файл и/или в stderr."""

    def __init__(
        self,
        enabled: bool = True,
        log_file: str | None = None,
        user_id: str = "mcp-client",
    ):
        self._enabled = enabled
        self._log_file: Path | None = Path(log_file) if log_file else None
        self._user_id = user_id

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "AuditLogger":
        """Собрать из секции telemetry конфига."""
        config = config or {}
        telemetry = config.get("telemetry", {}) if isinstance(config, dict) else {}
        if not isinstance(telemetry, dict):
            telemetry = {}

        return cls(
            enabled=bool(telemetry.get("audit_log", False)),
            log_file=telemetry.get("audit_log_file"),
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    def log_call(
        self,
        tool_name: str,
        plugin_id: str,
        params: dict[str, Any] | None,
        status: str,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        """Записать аудит-запись о вызове инструмента."""
        if not self._enabled:
            return

        record: dict[str, Any] = {
            "timestamp": time.time(),
            "user_id": self._user_id,
            "tool": tool_name,
            "plugin": plugin_id,
            "status": status,
            "duration_ms": round(duration_ms, 3),
            "params": sanitize_params(params),
        }
        if error:
            record["error"] = error[:1000]

        line = json.dumps(record, ensure_ascii=False, default=str)

        try:
            if self._log_file:
                self._log_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self._log_file, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            else:
                logger.info(line)
        except Exception as e:  # аудит не должен ронить инструменты
            logger.warning(f"Audit log write failed: {e}")


class Timer:
    """Простой контекстный менеджер для замера длительности."""

    def __enter__(self) -> "Timer":
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.elapsed_ms = (time.perf_counter() - self.start) * 1000