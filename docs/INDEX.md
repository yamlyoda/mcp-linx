# docs/INDEX.md — навигация по документации (что где, когда читать)

> Правило: открывать ОДИН нужный раздел диапазоном строк, а не файл целиком.
> Полные размеры — в скобках, чтобы оценивать цену чтения.

## Корень

| Файл | Строк | Когда читать |
|---|---|---|
| `AGENTS.md` | ~130 | ВСЕГДА первым: карта репо, команды, факты, протоколы |
| `README.md` | 372 (EN) | Только нужная секция: Installation / Running / Docker / Configuration / Security |
| `README.ru.md` | 371 (RU) | Русская версия; EN — канон при расхождениях |
| `TODO.md` | ~160 | Живой бэклог: пункты A–G + волны §G. Читать целиком можно (короткий) |
| `CHANGELOG.md` | 324, append-only | Архив фаз. Только `tail -40`, никогда целиком |
| `SECURITY.md` | 254 | Таблица сканеров §«CI» (Trivy `@v0.36.0`); Security Issues — по нужному ID |
| `REMOTE_TROUBLESHOOTING.md` | 171 | Роадмап remote/SSH: статусы #1–#8 (что FIXED, что TODO) |
| `HARNESS_ANALYSIS.md` | 194 | Идеология Harness vs текущее состояние; для задач волны 5 |
| `diagnosis_state.md` | 118, gitignored | Локальные креды/инциденты. НЕ читать в обычных задачах, НЕ коммитить (C7) |

## docs/

| Файл | Строк | Когда читать |
|---|---|---|
| `docs/ARCHITECTURE.md` | 168 | Устройство плагинов/адаптеров/harness; для новых фич |
| `docs/DEVELOPMENT.md` | 201 | Setup, структура, запуск, тесты — для onboard-задач |
| `docs/SKILLS.md` | 30 | Индекс system tools (краткий, можно целиком) |
| `docs/INCIDENT_504.md` | 111 | Разбор 504 nginx→Go→PostgreSQL + runbook; для netdiag/pg-задач |
| `docs/skills/` | — | По одному файлу на скилл, по мере нужды |

## config / CI

| Файл | Когда читать |
|---|---|
| `config/settings.yaml` | Дефолты плагинов/hosts; валидация — `python -c "yaml.safe_load(...)"` |
| `.github/workflows/ci.yml` | Джобы lint-typecheck/test/security/docker-build; валидация — `yaml.safe_load` |
| `Dockerfile` | Два слоя правок B10: apt `--only-upgrade` + pip `setuptools==84.0.0`; ENTRYPOINT `python -m mcp_linx.main` |
| `pyproject.toml` | Зависимости, ruff/mypy/bandit/pytest-настройки (104 строки, можно целиком) |
