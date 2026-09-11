"""Компакция контекста как плагин.

Управляет размером контекста для длинных сессий.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class ContextCompactor(ABC):
    """Базовый класс компакции контекста.

    Компакция уменьшает размер контекста для предотвращения
    переполнения токенов в длинных сессиях.
    """

    @abstractmethod
    def compact(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Компакция списка сообщений.

        Args:
            messages: Список сообщений для компакции

        Returns:
            Откомпактированный список сообщений
        """
        ...

    @abstractmethod
    def should_compact(self, messages: list[dict[str, Any]]) -> bool:
        """Проверить, нужна ли компакция.

        Args:
            messages: Список сообщений

        Returns:
            True если компакция нужна
        """
        ...


class SlidingWindowCompactor(ContextCompactor):
    """Скользящее окно.

    Оставляет только последние N сообщений.
    """

    def __init__(self, max_messages: int = 50):
        self._max_messages = max_messages

    def compact(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Оставить только последние N сообщений."""
        if len(messages) <= self._max_messages:
            return messages
        return messages[-self._max_messages :]

    def should_compact(self, messages: list[dict[str, Any]]) -> bool:
        """Проверить превышение лимита."""
        return len(messages) > self._max_messages


class TokenLimitCompactor(ContextCompactor):
    """Компакция по лимиту токенов.

    Удаляет старые сообщения при превышении лимита токенов.
    """

    def __init__(self, max_tokens: int = 100000):
        self._max_tokens = max_tokens

    def compact(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Удалять старые сообщения пока не уложимся в лимит."""
        # Простая оценка: ~4 символа на токен
        while self._estimate_tokens(messages) > self._max_tokens and len(messages) > 1:
            # Удаляем второе сообщение (сохраняем системное первым)
            if len(messages) > 2:
                messages.pop(1)
            else:
                break
        return messages

    def should_compact(self, messages: list[dict[str, Any]]) -> bool:
        """Проверить превышение лимита токенов."""
        return self._estimate_tokens(messages) > self._max_tokens

    def _estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Оценка количества токенов (грубо: ~4 символа на токен)."""
        total_chars = sum(len(str(m)) for m in messages)
        return total_chars // 4


class SummaryCompactor(ContextCompactor):
    """Компакция через суммаризацию.

    Заменяет старые сообщения на их краткое содержание.
    Требует LLM для суммаризации.
    """

    def __init__(self, keep_recent: int = 10, summarize_older: bool = True):
        self._keep_recent = keep_recent
        self._summarize_older = summarize_older

    def compact(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Суммаризовать старые сообщения."""
        if len(messages) <= self._keep_recent:
            return messages

        # Оставляем последние N сообщения как есть
        recent = messages[-self._keep_recent :]
        older = messages[: -self._keep_recent]

        if self._summarize_older and older:
            # В реальности здесь был бы вызов LLM для суммаризации
            summary = {
                "role": "system",
                "content": f"[Summary of {len(older)} earlier messages]",
            }
            return [summary] + recent

        return recent

    def should_compact(self, messages: list[dict[str, Any]]) -> bool:
        """Проверить необходимость компакции."""
        return len(messages) > self._keep_recent
