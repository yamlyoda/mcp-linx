"""Rate limiting для MCP-Linx.

Предотвращает перегрузку сервера: скользящее окно по каждому инструменту.
Настраивается через конфиг: security.rate_limit_max_calls, security.rate_limit_window_seconds.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Any

from mcp_linx.security import SecurityError


class RateLimiter:
    """Скользящее окно лимитов: max_calls вызовов за window_seconds на инструмент."""

    def __init__(self, max_calls: int = 60, window_seconds: int = 60):
        if max_calls < 1:
            raise ValueError("max_calls must be >= 1")
        if window_seconds < 1:
            raise ValueError("window_seconds must be >= 1")
        self._max_calls = max_calls
        self._window_seconds = window_seconds
        self._calls: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @classmethod
    def from_config(cls, sec: dict[str, Any] | None) -> RateLimiter:
        sec = sec or {}
        return cls(
            max_calls=int(sec.get("rate_limit_max_calls", 60)),
            window_seconds=int(sec.get("rate_limit_window_seconds", 60)),
        )

    def check(self, key: str) -> bool:
        """Проверить, можно ли выполнить вызов. True = можно."""
        now = time.monotonic()
        with self._lock:
            queue = self._calls[key]
            while queue and now - queue[0] > self._window_seconds:
                queue.popleft()

            if len(queue) >= self._max_calls:
                return False

            queue.append(now)
            return True

    def enforce(self, key: str) -> None:
        """Проверить вызов и бросить исключение при превышении лимита."""
        if not self.check(key):
            raise SecurityError(
                f"Rate limit exceeded for '{key}': {self._max_calls} calls "
                f"per {self._window_seconds}s. Retry later."
            )
