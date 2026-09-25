"""C10: `docs/INDEX.md` не должен расходиться с реальными файлами.

Index заявляет точные размеры документов, а он сам — «карта» репозитория, поэтому
дрейф делает его вредным. Тест проверяет две вещи:

1. заявленное число строк совпадает с фактическим;
2. каждый `*.md` в корне и в `docs/` упомянут в INDEX (новый документ нельзя
   «забыть»).

`docs/INDEX.md` из проверки размеров исключён (самоссылка).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INDEX = REPO_ROOT / "docs" / "INDEX.md"

# | `path/to/file.md` | 123 | описание
_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(\d+)")
_PATH_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|")


def _claimed_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in INDEX.read_text(encoding="utf-8").splitlines():
        match = _ROW.match(line)
        if match:
            counts[match.group(1)] = int(match.group(2))
    return counts


def _actual_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _documented_paths() -> set[str]:
    return {
        match.group(1)
        for match in (
            _PATH_ROW.match(line) for line in INDEX.read_text(encoding="utf-8").splitlines()
        )
        if match
    }


def test_claimed_line_counts_match_files():
    drift: list[str] = []
    for relative, claimed in sorted(_claimed_counts().items()):
        path = REPO_ROOT / relative
        if not path.is_file():
            drift.append(f"{relative}: файла нет (заявлено {claimed} строк)")
            continue
        actual = _actual_count(path)
        if actual != claimed:
            drift.append(f"{relative}: INDEX заявляет {claimed}, фактически {actual}")

    assert not drift, "docs/INDEX.md расходится с файлами — обновите таблицу:\n  " + "\n  ".join(
        drift
    )


def test_every_markdown_document_is_listed():
    """Новый документ должен быть добавлен в INDEX (иначе карта неполна)."""
    candidates = sorted(p for p in REPO_ROOT.glob("*.md"))
    candidates += sorted(p for p in (REPO_ROOT / "docs").glob("*.md"))

    missing = [
        str(p.relative_to(REPO_ROOT))
        for p in candidates
        if p.name != "INDEX.md" and str(p.relative_to(REPO_ROOT)) not in _documented_paths()
    ]

    assert not missing, f"документы отсутствуют в docs/INDEX.md: {missing}"


def test_index_lists_the_moved_harness_analysis():
    """C6: файл живёт в docs/, а не в корне."""
    assert "docs/HARNESS_ANALYSIS.md" in _documented_paths()
    assert not (REPO_ROOT / "HARNESS_ANALYSIS.md").exists()
