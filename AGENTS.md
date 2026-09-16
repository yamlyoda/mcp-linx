# AGENTS.md — карта репозитория и протокол работы (экономия токенов)

> Читать этот файл ПЕРВЫМ в каждой сессии. Он заменяет разведку:
> структура, команды, проверенные факты и правила чтения зафиксированы здесь,
> перевыяснять их поиском по дереву НЕ нужно.

## 1. Карта репо

```
src/mcp_linx/
├── main.py                 # entry point: python -m mcp_linx.main (единственный рабочий запуск)
├── __init__.py             # from mcp_linx.main import main (затеняет модуль — см. A1)
├── multihost.py            # HostRegistry, именованные SSH-цели
├── security.py             # SecurityGuard (validate_command; validate_host НЕ вызывается — см. A3)
├── audit.py / ratelimit.py / types.py / context_aggregator.py
├── adapters/               # base.py, ssh.py (paramiko), ssh_pool.py, docker.py
├── plugins/                # base.py + 10 плагинов: linux nginx docker postgres
│                           #   redis systemd netdiag kubernetes prometheus loki
│                           #   каждый: __init__.py + tools.py
└── harness/                # agent_loop.py context.py sandbox.py plugin_manager.py
config/settings.yaml        # дефолтный конфиг (CONFIG_PATH переопределяет)
tests/unit/  tests/integration/   # unit: 111 passed, 2 skipped; integration требует Docker
```

`src/` — ~7.4k строк / 37 файлов. Самый большой: `context_aggregator.py` (433).
Документация: `README.md` (372 строки, EN — канон) + `README.ru.md` (371, RU),
`CHANGELOG.md` (архив фаз, append-only),
`TODO.md` (живой бэклог A–G + волны), `SECURITY.md`, `REMOTE_TROUBLESHOOTING.md`,
`HARNESS_ANALYSIS.md`, `docs/` (ARCHITECTURE, DEVELOPMENT, SKILLS, INCIDENT_504, skills/).
Навигация по докам — `docs/INDEX.md` (что где, когда читать).

## 2. Команды (venv проекта; глобальный python НЕ использовать)

```bash
.venv/bin/python -m pytest -q          # гейт тестов (ожидается 111 passed, 2 skipped)
.venv/bin/ruff check src tests         # линтер (line-length 100, правила: E F I N W UP B C4 SIM)
.venv/bin/ruff format --check src tests
.venv/bin/python -m mypy src/mcp_linx  # strict=true
.venv/bin/bandit -c pyproject.toml -r src/mcp_linx -q   # только src/, tests исключены
pre-commit run --all-files             # всё разом перед коммитом
docker build -t mcp-linx:ci .          # образ для Trivy-гейта (job docker-build в CI)
trivy image mcp-linx:ci --format json --severity HIGH,CRITICAL --ignore-unfixed --skip-version-check
```

Запуск сервера: ТОЛЬКО `python -m mcp_linx.main` (Dockerfile ENTRYPOINT, README).
НЕ работают: `.venv/bin/mcp-linx` (console script на async-функцию — A1),
`python -m mcp_linx` (нет `__main__.py` — A1).

## 3. Проверенные факты (не перевыяснять)

- `setuptools==84.0.0` — max на PyPI; `84.1.0` НЕ существует (билд падает).
  `kubernetes` держит `setuptools` как transitive → удалять нельзя, только upgrade.
  `wheel>=0.46.2`. Закрывают CVE-2026-24049 / CVE-2026-23949.
- Базовый образ `python:3.11-slim` уже содержит deb822 `debian.sources`
  (suites: trixie trixie-updates trixie-security). Кастомные `.list`-файлы НЕ нужны
  (ломают билд, exit 100). Debian-пакеты с CVE чинятся строкой
  `apt-get install --only-upgrade gzip libpcre2-8-0 libsqlite3-0`.
- CI: `aquasecurity/trivy-action` — теги ТОЛЬКО с префиксом `v` (`@v0.36.0`);
  ref без `v` не резолвится. `ignore-unfixed: true` — гейт только по CVE с патчем.
- `Settings` — pydantic-settings, читает `.env`; НО: без `env_prefix` имена
  `LINX_*` из docker-compose НЕ подхватываются (A10); креды плагинов через
  `${VAR}` НЕ подставляются (A4); `Settings.plugins` нигде не используется (A10).
- `validate_host()` не вызывается в `src/` (A3); `shutdown_handler` — no-op,
  `plugin_manager_ref` пуст (A2); `audit_log_file` по дефолту
  `/var/log/mcp-linx/audit.log` — в контейнере неписуемо (A6).
- `diagnosis_state.md` — в `.gitignore`, kept local only. НЕ трогать (C7).
- Коммиты делает ТОЛЬКО пользователь. Агент правит файлы, не коммитит.

## 4. Протокол чтения (обязательно)

1. Задача начинается с `git status --porcelain` + `git log --oneline -3`, НЕ с `find`/`ls -R`.
2. Читать файлы ТОЛЬКО диапазоном строк (`start_line`/`end_line`), никогда целиком
   «на всякий случай». Исключение: файлы < 60 строк.
3. Доки: сначала `docs/INDEX.md`, затем ОДИН нужный раздел диапазоном.
   `CHANGELOG.md` — только `tail -40`. `README.md` — только нужная секция.
4. Поиск: один `search_codebase` с точным паттерном вместо веера широких запросов;
   `__pycache__/`, `.venv/`, `.mypy_cache/`, `.ruff_cache/` — игнорировать в выдаче.
5. Не перечитывать то, что уже зафиксировано здесь или в TODO (A–G) — ссылаться.
6. Тяжёлые команды (`docker build`, `trivy`, `pytest`) — один раз, с `tail`/jq-выборкой,
   НЕ полным логом. Повторный прогон только если менялся соответствующий слой.

## 5. Протокол задачи

- Формулировка задачи: `файл:строки + ожидаемое поведение + команда проверки`.
- Правки: малые диффы через `editor` (old_text ≤ ~100 строк на вызов).
- Валидация ОДИН раз в конце: `pytest -q | tail -3`, `git diff --stat`,
  плюс профильные гейты (ruff/mypy/bandit — если трогался `src/`).
- Артефакты сессии: обновить `TODO.md` (пункт A–G) — без переписывания истории.
- Вызов инструментов: команды — ТОЛЬКО `run_commands` (tool `shell` НЕ существует);
  `ask_question.options` — массив СТРОК, не объектов.
- Ответ пользователю: что изменено (файлы), как проверено (команда + результат),
  что осталось открыто. Без воды.

## 6. Чек-лист постановки задачи (для пользователя)

- [ ] Указан файл и строки (или ID пункта TODO: A1…G)?
- [ ] Описано ожидаемое поведение (до/после)?
- [ ] Указана команда приёмки (тест/скан/ручная проверка)?
- [ ] Волна из TODO.md §G (1–5) или внеплановый фикс?
