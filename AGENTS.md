# AGENTS.md — карта репозитория и протокол работы (экономия токенов)

> Читать этот файл ПЕРВЫМ в каждой сессии. Он заменяет разведку:
> структура, команды, проверенные факты и правила чтения зафиксированы здесь,
> перевыяснять их поиском по дереву НЕ нужно.

## 0. Статус сессии (обновлять в конце каждой задачи)

- 2026-09-25 (волна 17 ✅, код+тесты+docs): **E7** — read-only `linux_file_diagnostics`
  для проверки пути, `stat`/`namei`/`lsattr`, mount/space и свойств unit-а; опциональный
  `test -w` от service-user через строгий `runuser`-runner и `plugins.linux.privileged_tools`.
  `chattr` не автоматизируется. Обновлены CI/docs и добавлен отчёт по service.log.
  Гейт: 481 passed, 5 skipped; Ruff/mypy/Bandit/YAML/docs/diff — зелёные.

- 2026-09-25 (волна 14 ✅, код+тесты+docs): **C15** — покрытие tools плагинов:
  docker 28% → 100% (+17), k8s 29% → 92% (+19), netdiag 45% → 92% (+16),
  redis 45% → 91% (+13); unit **76% → 85%**, **418 passed**. Новые файлы:
  `test_docker_tools.py`, `test_kubernetes_tools.py`, `test_netdiag_tools.py`,
  `test_redis_tools.py`. **E6** — композитные system tools `diagnose_host` /
  `diagnose_web_service` в `agent_loop._register_system_tools` (параллельный
  `asyncio.gather` через `_invoke_tool`; недоступный tool → `skipped`),
  +7 тестов `TestDiagnoseTools`. Ловушка: `time.monotonic` патчить ТОЛЬКО как
  имя в неймспейсе модуля (`setattr(mod, "time", ...)`), не атрибут глобального
  `time` (его дёргает event loop). Убран мёртвый `get_config` из README EN/RU.
  Docs: README EN/RU (System Tools + §Security: `diagnose_*` внутри обходят
  rate-limit/audit), SKILLS (+2 системных tool, 3 → 5), TODO (C15/E6/волна 14).

- 2026-09-25 (волна 15 ✅, тесты): **C16** — покрытие tools PostgreSQL/Linux/Nginx:
  новые `test_postgres_tools.py`, `test_linux_tools.py`, `test_nginx_tools.py`; целевые
  модули: PostgreSQL 100%, Linux 96%, Nginx 97% (были 42/56/68%). Проверены
  успешные ответы, fallback-ветки, валидация параметров, degraded/error-сценарии,
  shell/network-парсинг и HTTP-проверки без внешних PostgreSQL/Nginx/SSH-сервисов.
  Runtime-код и MCP-контракт не менялись; пользовательская документация не требуется.
- 2026-09-25 (волна 16 ✅, CI): docs-guard больше не требует локальный
  gitignored `diagnosis_state.md`; его счётчик заменён на `—`. Trivy выявил
  21 patchable HIGH в bind9 из `dnsutils`; runtime-слой обновляет
  `bind9-dnsutils` до `1:9.20.29-1~deb13u1`. Docker build OK; Trivy v0.74:
  0 HIGH/CRITICAL, 0 secrets, exit 0. Полный pytest: 472 passed, 5 skipped.
- 2026-09-16: A1 ✅ (sync `main()` + `__main__.py`), A2 ✅ (`_main_async` + stop_event + тест),
  A5 ✅ / A6 ✅ (docs-only в `settings.yaml`), B10 ✅ (Trivy 0 HIGH/CRITICAL),
  тесты склеены 5→2 + `conftest.make_plugin`, README split 498→372+371,
  создан `AGENTS.md` + `docs/INDEX.md`. Гейт: **114 passed, 2 skipped**.
- 2026-09-16 (волна 1): D1 ✅ / D4 ✅ / D5 ✅ (docs-only), C1 🟡 частично (authors; LICENSE/py.typed открыты).
- 2026-09-16 (волна 2, код): A1 ✅ / A2 ✅ (`_main_async` + `stop_event` + тест), A5 ✅ / A6 ✅ (docs-only).
- 2026-09-16 (волна 3, код): A4 ✅ (`_expand_env_vars` в `load_config` + 4 теста) / A3 ✅ (wire-up `validate_host` в linux/nginx/systemd до `_resolve_adapter`; семантика `hosts:` vs `allowed_hosts` в `settings.yaml:44-46` + 2 теста).
  A7 ✅ / A10 ✅ (закрыты 2026-09-17 — чистка, см. ниже), A9 ✅ (rate-limit жив и задокументирован).
- 2026-09-17 (волна 3, доводка A9 CLOSED): `SecurityGuard.apply_timeout()` **удалён** (мёртвая заглушка, 0 вызовов); тезис аудита про «бессмысленные `# nosec` B507/B601» **опровергнут** probe'ом (аннотации load-bearing, bandit-WARNING ложный); `command_timeout_seconds` проведён **в дефолты плагинов** (`SecurityGuard.command_timeout` → `DiagnosticPlugin.command_timeout` → `timeout = self.command_timeout` в `_run*` 6 плагинов; explicit per-tool timeout перекрывает). Тесты: `tests/unit/test_command_timeout.py` (+15).
- Гейт волны 3: **135 passed, 2 skipped**; `ruff check` / `ruff format --check` / `mypy` / `bandit` зелёные (bandit = 0 issues; 4 WARNING про nosec — ложные).
- 2026-09-17 (C4 ✅): создан `.env.example` — фактические имена `Settings` (`MCP_SERVER_NAME`, `MCP_SERVER_VERSION`, `CONFIG_PATH`, `LOG_LEVEL`, `AGENT_LOOP`; `PLUGINS` не поддерживается: поле удалено в A10 ✅), секреты `${VAR}` (A4: `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `PROMETHEUS_TOKEN`, `LOKI_TOKEN` с файлами:строками), `SSH_KEY_DIR` (compose). Проверено прогоном: `Settings()` из `.env` мапит все имена, `${VAR}` раскрывается в реальном `settings.yaml`, файл не игнорируется (`!.env.example` → `??`). Указатель в README / README.ru.
- 2026-09-17 (A7 ✅ / A10 ✅, чистка): из `settings.yaml` удалена мёртвая секция
  `logging:` (на её месте NOTE-указатель: логирование = env `LOG_LEVEL` → `main.py:49-53`),
  `structlog` убран из `pyproject.toml`; удалено мёртвое поле `Settings.plugins`
  (env `PLUGINS` игнорируется и не ломает `extra='forbid'`). Резервы с inline-NOTE
  «НЕ читается»: `environment.mode`/`debug`, `telemetry.log_level`. `env_prefix` не вводим.
  **Волна 3 закрыта** (A3/A4/A7/A9/A10/C4).
- 2026-09-17 (волна 4 ✅): B1–B7, B9 (actions SHA + Dependabot), C3 (`py.typed`), C5 (project URLs). **204 unit passed, coverage 62.27%**, CI gate 60%; integration **5 passed, 2 skipped** (локально нет redis-cli; CI устанавливает redis-tools). Python matrix 3.11/3.12/3.13; 3.12/3.13 ещё не запускались локально. Ruff/format/mypy/bandit зелёные. Wheel/sdist содержат py.typed и URLs; Docker build + MCP stdio smoke OK. Runtime-код не менялся. Отказы rate-limit не аудируются — текущее поведение зафиксировано тестом.
- 2026-09-17 (волна 5, A8 ✅): `SSHAdapter` — тонкая обёртка над `SSHConnectionPool` (свой пул на адаптер)
  + `exec_command_sync`; удалены `_connect_sync`/`_execute_command_sync`/`assert` (nosec B101). Унаследованы
  connect_timeout=10 и keepalive=30s, переиспользование и reconnect соединений. `ping()` по returncode.
  Тесты: `test_ssh_policy.py` +6 unit (исправление прежнего +11: сравнивались unit и full; fake получил `get_transport`/`exec_command`; connect_kwargs теперь с `timeout: 10`).
- 2026-09-17 (docs, D2/D3 ✅): исправлены README EN/RU, DEVELOPMENT, SECURITY,
  .env.example и containers skill; в §5 закреплено обязательное обновление docs
  вместе с кодом. Поправка A8: +6 unit, не +11 (смешивались unit и full).
  Прогон `pytest tests/ -q`: 215 passed, 2 skipped (терминальный wrapper сообщил
  ошибку завершения; итог pytest сохранён в логе). Runtime-код в этой задаче не менялся.
- 2026-09-17 (D6 ✅, docs/code): уточнены plugins.enabled (**пересмотрено в wave 6**:
  теперь это настоящий фильтр, а не init-only), границы readonly/rate-limit,
  env-настройки запуска, streaming, путь нового плагина.
  В src изменён только docstring DockerPlugin.prune_containers. Full pytest:
  215 passed, 2 skipped, PYTEST_EXIT=0; терминальная обёртка ошибается при закрытии.
  Ruff/format изменённого файла и mypy src — OK. Runtime-поведение не менялось.
- 2026-09-18 (волна 6 ✅, код+docs): `plugins.enabled` = активный набор плагинов.
  `PluginManager._enabled_ids()` + фильтр в `load_plugins()` → `get_tools()`,
  `health_check_all()`, `destroy_all()` автоматически работают по активному набору
  (раньше tools/health шли по всем, и tools исключённого плагина падали
  `RuntimeError: Plugin not initialized`). Неизвестный id в списке → warning.
  Удалены мёртвые ключи: секция `environment:` (mode/debug), `telemetry.log_level`
  и 10 per-plugin `enabled: true` (код их не читал). Новый
  `tests/unit/test_plugin_manager.py` (+11) с изоляцией `PLUGIN_REGISTRY` и тестом
  синхронности `settings.yaml::plugins.enabled` ↔ реестр. Docs: settings.yaml,
  README EN/RU, ARCHITECTURE, DEVELOPMENT.
  Гейт: **226 passed, 2 skipped, PYTEST_EXIT=0**; ruff check/format, mypy, bandit —
  зелёные; YAML-валидация и `git diff --check` — OK. Поведение: без `enabled` —
  10 плагинов/56 tools, с `enabled: [linux]` — 1 плагин/8 tools (было 10/56).

- 2026-09-18 (волны 7–10 ✅, код+docs): **релиз** — `LICENSE` (MIT) + PEP 639
  (`license = "MIT"`, `license-files`; classifier лицензии убран), статус Alpha в README,
  Dockerfile `FROM` по digest (оба стейджа), coverage unit **62.27% → 66.06%**, CI-гейт
  60 → **65**, локальный прогон на **Python 3.12: 245 passed** (3.13 недоступен).
  **docs** — `HARNESS_ANALYSIS.md` → `docs/`, `docs/INDEX.md` счётчики + тест-страж
  `tests/unit/test_docs_index.py`, раздел «PostgreSQL SSL modes» (README EN/RU),
  SECURITY.md: три «Critical Issues» помечены FIXED с проверкой по коду.
  **security** — `SecurityGuard.readonly` + `DockerPlugin.prune_containers` бросает
  `SecurityError` при readonly (A12); отказы rate-limit аудируются (A13); граница
  доверия stdio задокументирована (D7).
  **фичи** — E1 `exec_command_with_retry` (+`retry_params`, `SSHConnectionPool.drop`);
  E2 `SSHTunnel` (`direct-tcpip`) + wiring в `PostgresPlugin` (`ssh.tunnel: true`).
  Новые тесты: `test_adapters_local` (12), `test_context_compactors` (12),
  `test_docs_index` (3), `test_ssh_retry` (12), `test_ssh_tunnel` (7),
  `test_postgres_tunnel` (6), `TestDockerPruneReadonly` (6), `test_plugin_manager` (11).
  Гейт последней волны: **284 passed, 2 skipped, PYTEST_EXIT=0**; coverage unit
  **67.74%** при гейте 65 (279 unit-тестов); Python 3.12 — 279 passed, exit 0;
  ruff check/format, mypy, bandit — зелёные; YAML/tomllib, markdown-fences,
  `git diff --check` — OK. Integration не перезапускался: изменённые слои
  (docker-prune/readonly, SSH retry/tunnel, audit) покрыты unit-тестами и не
  пересекаются с `tests/integration/`.

- 2026-09-18 (волна 11 ✅, чистка+решения): удалён мёртвый `harness/sandbox.py`
  (208 строк, 0 вызовов, только реэкспорт) → `harness/__init__.py`, `HARNESS_ANALYSIS`
  (раздел 3 = «отклонено», Фазы 1/2/4 актуализированы, оценка 35% → ~65%),
  `ARCHITECTURE`, `DEVELOPMENT`, README EN/RU, AGENTS §1. Компакторы контекста
  оставлены осознанным резервом (C12: библиотечный API, ключи конфига не вводим).
  E5 `asyncssh` закрыт как **WON'T DO NOW** с обоснованием (TODO, REMOTE #7);
  C7 → no-op; убрана неточность «F#8-остаток» (F#8 закрыт ранее).
- 2026-09-18 (волна 12 ✅, тесты): покрытие unit **68.67% → 75%**, CI-гейт **65 → 72**.
  Новые файлы: `test_agent_loop_lifecycle.py` (+18; `agent_loop` 47% → 96% —
  `setup`/`run`/`shutdown`, системные tools, seed контекста, инжект `HostRegistry`),
  `test_main_startup.py` (+5; `main.py` 80% → 100% — старт сервера, cleanup в `finally`,
  ветка «сервер завершился первым», sync entrypoint), `test_observability_tools.py`
  (+24; `loki` 19% → 92%, `prometheus` 19% → 89%). Найдена и подтверждена ловушка
  `import mcp_linx.main as m` (возвращает функцию) — в тесте модуль берётся через
  `importlib.import_module`. Доки не менялись (только `TODO`/`AGENTS` + CI-гейт).

- 2026-09-18 (волна 13 ✅, код+docs): **E3** jump host/bastion —
  `SSHConnectionPool._connect` открывает `direct-tcpip` на бастионе и передаёт канал
  в `connect(sock=...)`, `_jump_config` маппит `jump_*` (наследуя `host_key_policy`/
  `known_hosts`), бастион закрывается вместе с целью (`_jump_clients`, `drop`,
  `close_all`); тесты `test_ssh_jump.py` (+9). **E4a** — k8s multi-cluster
  задокументирован (один кластер на инстанс, `kubeconfig`/`context`).
  **E4b** — PostgreSQL multi-target: `plugins.postgres.targets.<имя>` + `host` у `pg_*`
  (12 call-sites), свой коннект/туннель на таргет, кэш, закрытие в `destroy()`;
  тесты `test_postgres_targets.py` (+11). **C14** — opt-in E2E-тест реального SSH
  (`tests/integration/test_ssh_tunnel_e2e.py`: баннер через туннель, команда,
  переиспользование; скип без env). Docs: README EN/RU (jump host, PG multi-target,
  k8s multi-cluster), DEVELOPMENT (запуск E2E), settings.yaml, REMOTE #5.

- Открыты: **Python 3.13** и полный integration в CI (ожидают пуша), auth (F#13 —
  решение: вне объёма stdio, см. D7), сабагенты и подключение компакторов
  (осознанно не делаем — HARNESS_ANALYSIS).

## 1. Карта репо

```
src/mcp_linx/
├── main.py                 # entry point: sync main() -> _main_async(); запуски: mcp-linx, python -m mcp_linx, python -m mcp_linx.main
├── __main__.py             # python -m mcp_linx (A1)
├── __init__.py             # from mcp_linx.main import main (затеняет submodule — в тестах брать модуль через importlib)
├── multihost.py            # HostRegistry, именованные SSH-цели
├── security.py             # SecurityGuard (validate_command; validate_host в linux/nginx/systemd)
├── audit.py / ratelimit.py / types.py / context_aggregator.py
├── adapters/               # base.py, ssh.py (paramiko), ssh_pool.py, docker.py
├── plugins/                # base.py + 10 плагинов: linux nginx docker postgres
│                           #   redis systemd netdiag kubernetes prometheus loki
│                           #   каждый: __init__.py + tools.py
└── harness/                # agent_loop.py context.py plugin_manager.py
config/settings.yaml        # дефолтный конфиг (CONFIG_PATH переопределяет)
tests/unit/ (conftest.make_plugin — общий хелпер моков) + integration/   # integration требует Docker
```

`src/` — ~7.4k строк / 37 файлов. Самый большой: `context_aggregator.py` (433).
Документация: `README.md` (EN — канон) + `README.ru.md` (RU),
`CHANGELOG.md` (архив фаз, append-only), `LICENSE` (MIT),
`TODO.md` (живой бэклог A–G + волны), `SECURITY.md`, `REMOTE_TROUBLESHOOTING.md`,
`docs/` (ARCHITECTURE, DEVELOPMENT, SKILLS, INCIDENT_504, HARNESS_ANALYSIS, skills/).
Навигация по докам — `docs/INDEX.md` (что где, когда читать; счётчики строк
проверяются тестом `tests/unit/test_docs_index.py`).

## 2. Команды (venv проекта; глобальный python НЕ использовать)

```bash
.venv/bin/python -m pytest -q          # полный набор; результат фиксировать с датой и областью
.venv/bin/ruff check src tests         # линтер (line-length 100, правила: E F I N W UP B C4 SIM)
.venv/bin/ruff format --check src tests
.venv/bin/python -m mypy src/mcp_linx  # strict=true
.venv/bin/bandit -c pyproject.toml -r src/mcp_linx -q   # только src/, tests исключены
pre-commit run --all-files             # всё разом перед коммитом
docker build -t mcp-linx:ci .          # образ для Trivy-гейта (job docker-build в CI)
trivy image mcp-linx:ci --format json --severity HIGH,CRITICAL --ignore-unfixed --skip-version-check
```

Запуск сервера: `mcp-linx`, `python -m mcp_linx`, `python -m mcp_linx.main` (все рабочие после A1).
В тестах `import mcp_linx.main as m` возвращает ФУНКЦИЮ (shadowing в `__init__.py`) —
модуль брать через `importlib.import_module("mcp_linx.main")`.

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
- `Settings` — pydantic-settings, читает `.env`; имена БЕЗ префикса (`CONFIG_PATH`,
  `MCP_SERVER_NAME`, `MCP_SERVER_VERSION`, `LOG_LEVEL`, `AGENT_LOOP`); `LINX_*`
  не поддерживаются сознательно — `env_prefix` не вводим (A10 ✅). Креды плагинов —
  `${VAR}` / `${VAR:-default}` в `settings.yaml` (`load_config` → `_expand_env_vars`, A4 ✅;
  fail-open: нет переменной и нет default → warning + сырой текст). Поля `plugins` нет (A10 ✅).
- `plugins.enabled` — ЕДИНСТВЕННЫЙ переключатель состава плагинов (wave 6 ✅):
  фильтрует загрузку (`PluginManager.load_plugins` → `get_tools`/`health_check_all`/
  `destroy_all`). Пусто/нет ключа = все обнаруженные. Per-plugin `enabled: true`
  и секция `environment:`/`telemetry.log_level` УДАЛЕНЫ (мёртвые). Неизвестный id
  в списке → WARNING. Тест синхронности: `tests/unit/test_plugin_manager.py`.
- `validate_host()` вызывается в linux/nginx/systemd ДО `_resolve_adapter` (A3 ✅;
  семантика `hosts:` vs `allowed_hosts` — см. `config/settings.yaml`, ключ
  `security.allowed_hosts`); graceful shutdown
  живой: `_main_async` + `stop_event` (A2 ✅); `audit_log_file` по дефолту
  `/var/log/mcp-linx/audit.log` — в контейнере неписуемо, `AuditLogger` деградирует
  в stderr-warn (A6 ✅).
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
- **Код и документация меняются в одной задаче.** Перед правкой кода определить,
  какие инструкции, примеры, конфиги и описания поведения она затрагивает.
  До завершения обновить соответствующие разделы README (EN и RU), профильные
  `docs/`, `SECURITY.md`, `.env.example` и комментарии конфигурации — по применимости.
  Проверять не только новые возможности, но и удалённые API, дефолты, ограничения,
  команды запуска/тестов и изменения безопасности. Запись в TODO не заменяет docs.
- **Документация — часть приёмки:** сверить примеры с фактическим API/конфигом,
  выполнить доступные команды или безопасные probes, проверить ссылки и diff.
  Результаты тестов указывать с командой и областью (unit/integration/full),
  не переносить старые счётчики в текущие инструкции. Исторические результаты
  сохранять с датой; ошибочные записи явно исправлять. Волну не закрывать,
  пока остаются открытые пункты её объёма.
- Если изменение не требует документации (например, внутренний рефакторинг без
  изменения контракта), явно указать это и обоснование в итоговом отчёте/PR.
  Без обновления затронутой документации или такого обоснования задача не завершена.
- Вызов инструментов: команды — ТОЛЬКО `run_commands` (tool `shell` НЕ существует);
  `ask_question.options` — массив СТРОК, не объектов.
- Ответ пользователю: что изменено (файлы), как проверено (команда + результат),
  что осталось открыто. Без воды.

## 6. Чек-лист постановки задачи (для пользователя)

- [ ] Указан файл и строки (или ID пункта TODO: A1…G)?
- [ ] Описано ожидаемое поведение (до/после)?
- [ ] Указана команда приёмки (тест/скан/ручная проверка)?
- [ ] Волна из TODO.md §G (1–5) или внеплановый фикс?
