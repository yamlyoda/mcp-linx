"""Общие хелперы для unit-тестов (переиспользуются всеми test_*.py)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock


def make_plugin(plugin_class: type, methods: dict[str, Any]) -> MagicMock:
    """Мок плагина: методы из `methods` заменяются AsyncMock с заданным return_value."""
    plugin = MagicMock(spec=plugin_class)
    for name, ret in methods.items():
        setattr(plugin, name, AsyncMock(return_value=ret))
    return plugin
