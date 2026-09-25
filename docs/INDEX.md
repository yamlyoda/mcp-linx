# docs/INDEX.md — навигация по документации (что где, когда читать)

> Правило: открывать ОДИН нужный раздел диапазоном строк, а не файл целиком.
> Счётчики строк проверяются тестом `tests/unit/test_docs_index.py` — при правке
> документа обновите таблицу ниже (тест сообщит актуальные значения).

## Корень

| Файл | Строк | Когда читать |
|---|---|---|
| `AGENTS.md` | 230 | ВСЕГДА первым: карта репо, команды, факты, протоколы |
| `README.md` | 523 | Только нужная секция: Installation / Running / Docker / Configuration / Security |
| `README.ru.md` | 521 | Русская версия; EN — канон при расхождениях |
| `TODO.md` | 226 | Живой бэклог: пункты A–G + волны §G. Читать целиком можно (короткий) |
| `CHANGELOG.md` | 324 | Архив фаз. Только `tail -40`, никогда целиком |
| `SECURITY.md` | 279 | Аудит и чек-лист (§Security Checklist), ограничения подстановки секретов, CI-сканеры |
| `REMOTE_TROUBLESHOOTING.md` | 210 | Роадмап remote/SSH: статусы #1–#8 (что FIXED, что TODO) |
| `LICENSE` | — | MIT (текст; в INDEX не считается) |
| `diagnosis_state.md` | 118, gitignored | Локальные креды/инциденты. НЕ читать в обычных задачах, НЕ коммитить (C7) |

## docs/

| Файл | Строк | Когда читать |
|---|---|---|
| `docs/ARCHITECTURE.md` | 176 | Устройство плагинов/адаптеров/harness; для новых фич |
| `docs/DEVELOPMENT.md` | 296 | Setup, env/секреты, аудит, shutdown, тесты — для onboard-задач |
| `docs/SKILLS.md` | 30 | Индекс system tools (краткий, можно целиком) |
| `docs/INCIDENT_504.md` | 111 | Разбор 504 nginx→Go→PostgreSQL + runbook; для netdiag/pg-задач |
| `docs/HARNESS_ANALYSIS.md` | 195 | Идеология Harness vs текущее состояние (перенесён из корня, C6); статусы актуализированы 2026-09-18 |
| `docs/skills/` | — | По одному файлу на скилл, по мере нужды |

## config / CI

| Файл | Когда читать |
|---|---|
| `config/settings.yaml` | Дефолты плагинов/hosts; валидация — `python -c "yaml.safe_load(...)"` |
| `.github/workflows/ci.yml` | Джобы lint-typecheck/test/security/docker-build; валидация — `yaml.safe_load` |
| `Dockerfile` | Два слоя правок B10 + `FROM` по digest (C8); ENTRYPOINT `python -m mcp_linx.main` |
| `pyproject.toml` | Зависимости, PEP 639 license, ruff/mypy/bandit/pytest/coverage-настройки |
