"""Wave 7: компакторы контекста (`harness/context.py`) — чистые функции.

Покрываем три реализации `ContextCompactor`: скользящее окно, лимит токенов
и суммаризацию, включая граничные случаи (пустой список, граница лимита).
"""

from __future__ import annotations

from typing import Any

import pytest

from mcp_linx.harness.context import (
    ContextCompactor,
    SlidingWindowCompactor,
    SummaryCompactor,
    TokenLimitCompactor,
)


def _msgs(n: int, size: int = 10) -> list[dict[str, Any]]:
    """n сообщений, каждое ~`size` символов."""
    return [{"role": "user", "content": "x" * size} for _ in range(n)]


class TestSlidingWindowCompactor:
    def test_keeps_all_when_within_limit(self):
        compactor = SlidingWindowCompactor(max_messages=5)
        messages = _msgs(3)

        assert compactor.compact(messages) == messages
        assert compactor.should_compact(messages) is False

    def test_truncates_to_last_n(self):
        compactor = SlidingWindowCompactor(max_messages=2)
        messages = _msgs(5)
        messages[4]["marker"] = "last"

        result = compactor.compact(messages)

        assert len(result) == 2
        assert result[-1]["marker"] == "last"
        assert compactor.should_compact(_msgs(3)) is True

    def test_exact_boundary_is_not_compacted(self):
        compactor = SlidingWindowCompactor(max_messages=3)
        assert compactor.should_compact(_msgs(3)) is False

    def test_empty_list(self):
        compactor = SlidingWindowCompactor(max_messages=3)
        assert compactor.compact([]) == []


class TestTokenLimitCompactor:
    def test_within_limit_untouched(self):
        compactor = TokenLimitCompactor(max_tokens=10_000)
        messages = _msgs(3)

        assert compactor.compact(messages) == messages
        assert compactor.should_compact(messages) is False

    def test_drops_old_messages_until_fit(self):
        compactor = TokenLimitCompactor(max_tokens=100)
        messages = _msgs(10, size=100)

        result = compactor.compact(messages)

        assert 2 < len(result) < 10
        assert compactor._estimate_tokens(result) <= 100

    def test_stops_at_two_messages_even_if_limit_unreachable(self):
        """Лимит недостижим: сохраняются первое (системное) и последнее сообщение."""
        compactor = TokenLimitCompactor(max_tokens=1)
        messages = _msgs(5, size=100)

        result = compactor.compact(messages)

        assert result == [messages[0], messages[-1]]
        # Гарантия «минимум 2 сообщения» важнее лимита: should_compact остаётся True.
        assert compactor.should_compact(result) is True

    def test_token_estimate_is_chars_over_four(self):
        compactor = TokenLimitCompactor()
        assert compactor._estimate_tokens([]) == 0
        assert (
            compactor._estimate_tokens([{"a": 1}, {"b": 2}])
            == len(str({"a": 1}) + str({"b": 2})) // 4
        )


class TestSummaryCompactor:
    def test_within_limit_untouched(self):
        compactor = SummaryCompactor(keep_recent=3)
        messages = _msgs(2)

        assert compactor.compact(messages) == messages
        assert compactor.should_compact(messages) is False

    def test_prepends_summary_marker(self):
        compactor = SummaryCompactor(keep_recent=2)
        messages = _msgs(5)

        result = compactor.compact(messages)

        assert len(result) == 3
        assert result[0]["role"] == "system"
        assert "3 earlier messages" in result[0]["content"]
        assert result[1:] == messages[-2:]

    def test_without_summarization_keeps_only_recent(self):
        compactor = SummaryCompactor(keep_recent=2, summarize_older=False)
        messages = _msgs(5)

        assert compactor.compact(messages) == messages[-2:]
        assert compactor.should_compact(messages) is True


def test_compactor_is_abstract():
    with pytest.raises(TypeError):
        ContextCompactor()  # type: ignore[abstract]
