# TODO — Architecture Review & Findings

## Содержание

### Текущие находки и бэклог (Audit 2026-09-15)
- [Audit (top)](#audit)
- [A. Баги](#A)
- [B. Тесты и CI](#B)
- [C. Упаковка и гигиена](#C)
- [D. Документация](#D)
- [E. Роадмап фич](#E)
- [F. Ревизия прежних пунктов](#F)
- [G. Предлагаемый порядок работ (волны)](#G)

### История фаз / вехи
Архивный журнал фазовых логов 2026-09-10…2026-09-15 и закрытые пункты — в [`CHANGELOG.md`](./CHANGELOG.md) (перенесено из TODO.md для экономии чтения).

---

<a name="audit"></a>
## Audit 2026-09-15 — Known Issues & Backlog


**Контекст аудита:** multi-host реализован (`src/mcp_linx/multihost.py`, `src/mcp_linx/adapters/ssh_pool.py`); `discover_plugins()` → 10 плагинов / 56 tools + 3 system tools; `pytest` → 111 passed, 2 skipped. Ниже — результаты ревизии кода, конфига, CI и документации. **Изменений в код не вносилось** — только фиксация находок; каждая проверена чтением кода и/или прогоном.

Статус на момент аудита (2026-09-15): правки multi-host + docs уже закоммичены (HEAD на старте аудита `d75bc1f`, на данный момент — `9cb2503`); в рабочем дереве — `TODO.md` + новый `CHANGELOG.md`.

> NB: пункт «#### 10. ✅ Missing graceful shutdown — FIXED» (в архиве `CHANGELOG.md`) **не соответствует действительности** — см. A2. Запись «56 tools (было 51)» в конце исторического раздела — лог фазы, править не нужно.

<a name="A"></a>
### A. Баги (подтверждены воспроизведением)

- [ ] **A1 (P0). `mcp-linx` (console script) не запускает сервер.**
  - Repro: `$ .venv/bin/mcp-linx` → `<coroutine object main at 0x…>`, `RuntimeWarning: coroutine 'main' was never awaited`, `exit_code=1`.
  - Причина: `pyproject.toml` → `[project.scripts] mcp-linx = "mcp_linx.main:main"`, а `main` — `async def` (`iscoroutinefunction(main) is True`).
  - Сопутствующее: нет `src/mcp_linx/__main__.py` → `python -m mcp_linx` падает (`No module named mcp_linx.__main__`); `src/mcp_linx/__init__.py` (`from mcp_linx.main import main`) затеняет модуль `main` функцией. Работает только `python -m mcp_linx.main` (его используют Dockerfile и README).
  - Fix: sync-обёртка `def main() -> None: asyncio.run(_main())` + `__main__.py` + правка entry point/`__init__`; тест `iscoroutinefunction(main) is False`. Effort: ~30 мин.

- [ ] **A2 (P0). Graceful shutdown — мёртвый код, который вдобавок глотает SIGTERM/SIGINT.**
  - `main.py:118-128`: `plugin_manager_ref: dict = {}` **никогда не заполняется** → `shutdown_handler()` — no-op.
  - `loop.add_signal_handler(SIGTERM/SIGINT, …)` при этом **переопределяет** дефолтное поведение: SIGTERM больше не завершает процесс (в Docker `docker stop` → 10 с ожидания → SIGKILL), Ctrl+C перехватывается пустой задачей.
  - Реальная очистка (`destroy_all()` + `HostRegistry.close_all()`) срабатывает только в `finally` из `start_server()` при штатном возврате `mcp.run_async()`.
  - Fix: либо снять регистрацию хендлеров, либо вернуть `PluginManager` из `start_server()` и по сигналу корректно останавливать цикл и закрывать SSH-пул. Нужен тест на сигналы. Effort: ~1.5 ч.

- [ ] **A3 (P1). `allowed_hosts` — защита заявлена, но не работает; включение сломает multi-host.**
  - README (EN+RU, Security) обещает «Host validation: whitelist of allowed_hosts»; фактически `SecurityGuard.validate_host()` (`security.py:179`) **не вызывается в `src/`** — только из `tests/unit/test_security.py`.
  - Дефолты расходятся: `security.py` → `["localhost"]`; 6 плагинов → `["localhost","127.0.0.1"]`; `settings.yaml` → 2 записи.
  - Если включить «как есть» — сломается multi-host: `web-1` / `10.130.0.23` не в whitelist.
  - Развилка: (a) удалить метод и убрать обещание из README/SECURITY.md, либо (b) реализовать с моделью «`hosts:` = доверенные SSH-таргеты, `allowed_hosts` = разрешённые probe-цели» и вызывать при валидации входных параметров. Effort: 1–3 ч.

- [ ] **A4 (P0). Секреты из env не реализованы, хотя обещано — в том числе в security-отчёте.**
  - Env читается только через `pydantic_settings.BaseSettings` для настроек сервера (`main.py:29-37`) и **не покрывает** креды плагинов: подстановки `${VAR}` в YAML нет, `os.environ`/`getenv` в коде — **0** вхождений. Секрет задаётся только plaintext в `config/settings.yaml`.
  - Обещано в: `settings.yaml` (`# из env: POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `PROMETHEUS_TOKEN`, `LOKI_TOKEN`), `docker-compose.yml` (`# LINX_SSH_PASSWORD: ${LINX_SSH_PASSWORD}` — код эту переменную не читает, см. A10), README (`password: null  # prefer env / key auth`), **`SECURITY.md:187/249`** («No hardcoded secrets — Passwords from config/env», «`config/settings.yaml` | ✅ Clean | Passwords from env»).
  - Fix: раскрытие `${VAR}` / `${VAR:-default}` при загрузке конфига + тесты (нет переменной / default / кавычки), синхронизировать доки. Effort: ~2 ч.

- [ ] **A5 (P2). `postgres.ssh.tunnel_host` / `tunnel_port` — мёртвые ключи конфига.**
  - Есть в `settings.yaml`; REMOTE_TROUBLESHOOTING #2 помечает «Not implemented!». Либо реализовать (sshtunnel), либо удалить/пометить. Effort: 1–4 ч.

- [ ] **A6 (P1). Дефолтный audit-лог нерабочий в рекомендованном Docker-деплое.**
  - `telemetry.audit_log: true` + `audit_log_file: "/var/log/mcp-linx/audit.log"`: пользователь `mcp` в контейнере не может создать `/var/log/mcp-linx` → `PermissionError` → warning **на каждый вызов инструмента**, аудит фактически теряется.
  - Fix: `audit_log_file: null` (вывод в stderr) по умолчанию + том в docker-compose для файлового аудита + docs. Effort: ~1 ч.

- [ ] **A7 (P2). Секция `logging:` в `settings.yaml` мертва; `structlog` не используется.**
  - Нет `logging.config.dictConfig`; `structlog` импортируется **0** раз, но стоит в `dependencies`; `environment.mode`/`debug` не читаются, `telemetry.log_level` — тоже. Единственное чтение уровня: `main.py:44-45` из `Settings.log_level` (env `LOG_LEVEL`) + `basicConfig`. Т.е. мертвы: секция `logging:`, `telemetry.log_level`, `environment.mode`/`debug`.
  - Fix: применить `dictConfig(config["logging"])` **или** удалить секцию и зависимость (уменьшит образ). Effort: 1–2 ч.

- [ ] **A8 (P1). Дублирование SSH-логики: `SSHAdapter` vs `SSHConnectionPool`.**
  - `SSHAdapter` — копия host-key policy / known_hosts / connect / exec, но **без** `connect_timeout` и без `set_keepalive` (в пуле оба есть) и без переиспользования соединений. Два код-пути → расхождение поведения.
  - Fix: `SSHAdapter` как тонкая обёртка над `SSHConnectionPool` + `exec_command_sync` (единый код-путь). Effort: ~2 ч.

- [ ] **A9 (P2). Заглушки и мёртвый/недоступный API.**
  - `SecurityGuard.apply_timeout()` возвращает `func` без изменений и не используется.
  - `# nosec B601` в `SSHAdapter.ping()` (`adapters/ssh.py:114`) стоит на `timeout=5`, а не на `exec_command` (корректные аннотации — `ssh.py:151`, `ssh_pool.py:116`) → аннотация на строке 114 бессмысленна.
  - `rate_limit_max_calls` / `rate_limit_window_seconds`: отсутствуют в `settings.yaml` и не упомянуты в README/docs → лимит 60/60 фактически зашит. Effort: ~1 ч.

- [ ] **A10 (P2). Объявленные env-переменные и настройки не подключены.**
  - `Settings.plugins` (env `PLUGINS`, дефолт `"linux,nginx,docker,postgres"`) **не используется нигде** — состав плагинов определяет только `config/settings.yaml::plugins.enabled` через `PluginManager.load_plugins()`. Настройка вводит в заблуждение (и не соответствует факту 10 плагинов).
  - У `Settings` нет `env_prefix`, поэтому предложенные в `docker-compose.yml` имена `LINX_LOG_LEVEL` / `LINX_SSH_PASSWORD` **не будут прочитаны**: pydantic-settings ждёт `LOG_LEVEL`, `CONFIG_PATH`, `MCP_SERVER_NAME`, `MCP_SERVER_VERSION`, `AGENT_LOOP`.
  - Fix: либо `env_prefix="LINX_"` и приведение имён, либо правка имён в compose/README к фактическим полям. Effort: ~1 ч.

<a name="B"></a>
### B. Тесты и CI

- [ ] **B1. Нет тестов на ядро оркестрации** — `main.py` (`load_config`, `get_agent_loop`, сигналы) и `harness/agent_loop.py::_make_handler` (rate-limit → error-ответ, добавление `metadata`, обновление `ContextAggregator`, audit в `finally`, ветка `status if "status" in locals()`). Effort: ~2 ч.
- [ ] **B2. Нет тестов адаптеров/плагинов** `docker.py`, а также postgres/redis/kubernetes/prometheus/loki (частично покрыты только плагинными `test_new_plugins*`). Effort: ~3 ч.
- [ ] **B3. Покрытие никогда не измерялось:** `pytest-cov` не установлен, хотя `[tool.coverage]` в pyproject есть. → добавить `pytest-cov`, снять baseline, затем `--cov-fail-under` в CI. Effort: ~1 ч.
- [ ] **B4. CI не гоняет integration-тесты**, хотя `tests/docker-compose.test.yml` и маркер `integration` есть, а раннер имеет Docker. Добавить job `pytest -m integration`. Effort: ~1 ч.
- [ ] **B5. CI-проверка discovery слишком слабая:** `assert n >= 10 and len(tools) >= 50` при факте 10/56 → заменить на точные `== 10` / `== 56` (ловит дрейф счётчиков). Effort: 15 мин.
- [ ] **B6. Матрица CI = только Python 3.11**, а classifiers заявляют 3.11–3.13 → добавить 3.12/3.13. Effort: 15 мин.
- [ ] **B7. Нет теста на дефолтную SSH-политику** (`RejectPolicy` при отсутствии `host_key_policy`). Effort: 15 мин.

- [x] **B8. CI падал на резолве `aquasecurity/trivy-action@0.24.0`** — у экшена все теги идут с префиксом `v`, ref без префикса не существует («Unable to resolve action… unable to find version 0.24.0»). ✅ FIXED 2026-09-15 → `@v0.36.0` + синхронизирован `SECURITY.md:211`.
- [ ] **B9. Рассмотреть пиннинг third-party экшенов по commit SHA** (сейчас все — по тегам: `@v4`, `@v5`, `@v6`, `@v2`, `@v0.36.0`). У trivy-action релизы immutable (`immutable: true`), так что переопределить тег нельзя, но SHA-пиннинг + `dependabot.yml` — надёжнее.

- [x] **B10 (FIXED 2026-09-15). CI `docker-build` падал на Trivy.**
  - Двойной fix:
    1. **ci.yml**: `ignore-unfixed: true` → из 76 HIGH/CRITICAL осталось 2 реально exploitable (с патчем).
        2. **Dockerfile (runtime-stage)**: `setuptools` + `wheel` нельзя удалить (`kubernetes` держит `setuptools` как transitive), поэтому прокачаны до патч‑версий: `setuptools>=83` + `wheel>=0.46.2` — устраняют CVE-2026-24049 (wheel) и CVE-2026-23949 (jaraco.context через setuptools). Версии совпадают с dev‑пиннией в `pyproject.toml:48`.
  - Итог после rebuild: ожидаемо 0 HIGH/CRITICAL (перепроверть в CI). Полный per-CVE лист — в артефакте `trivy-results` (json).
  - B9 (SHA-пиннинг `FROM` + third-party-action) остаётся open — follow-up.

<a name="C"></a>
### C. Упаковка и гигиена репозитория

- [ ] **C1. Нет файла `LICENSE`**, при этом README: «MIT» и pyproject: `license = {text = "MIT"}`; classifier `Development Status :: 3 - Alpha` конфликтует с `version = "1.0.0"`. → добавить `LICENSE` (+ `license-files`, PEP 639), согласовать статус разработки.
- [x] **C2. `CHANGELOG.md` создан (FIXED 2026-09-15)** — исторические фазовые логи + вехи перенесены туда; `TODO.md` сокращён до живого бэклога + TOC.
- [ ] **C3. Нет `py.typed`** (PEP 561) при mypy strict и типизированном публичном API.
- [ ] **C4. Нет `.env.example`**, хотя `pydantic-settings` читает `.env` (`main.py:31`, `env_file=".env"`) и `.gitignore` разрешает `!.env.example`. Задокументировать фактически поддерживаемые имена: `CONFIG_PATH`, `LOG_LEVEL`, `MCP_SERVER_NAME`, `MCP_SERVER_VERSION`, `AGENT_LOOP` (+ `PLUGINS`, если починить — A10); связано с A4.
- [ ] **C5. Метаданные-заглушки:** `authors = mcp-linx <mcp-linx@example.com>`; нет `[project.urls]` (Homepage/Repository/Issues).
- [ ] **C6. `HARNESS_ANALYSIS.md` лежит в корне** — внутренний анализ, тогда как README ведёт список документации в `docs/`. Переместить или оставить осознанно.
- [ ] **C7.** `diagnosis_state.md` — корректно в `.gitignore` («креды, kept local only»), **не трогать**.

<a name="D"></a>
### D. Документация (следует за фиксами кода)

- [ ] **D1.** README (EN+RU, Security): убрать или исправить пункт про `allowed_hosts` — после решения по A3.
- [ ] **D2.** Добавить раздел про env-переменные (реальные имена полей `Settings`, см. A10) и `${VAR}` (A4), audit-лог и путь к нему (A6), корректное завершение по SIGTERM / `docker stop` (A2). Сейчас в `docs/DEVELOPMENT.md` про env **нет ничего**.
- [ ] **D3.** README Configuration: пометить/убрать `tunnel_host` (A5) и секцию `logging:` (A7); задокументировать `rate_limit_*` (A9).
- [ ] **D4.** REMOTE_TROUBLESHOOTING #6 «Connection health monitoring» помечен как TODO, **хотя частично уже реализован**: в пуле есть `transport.set_keepalive(30)`, проверка `is_active()` и реконнект мёртвого клиента. Остаётся ретрай для «живого, но разорванного» транспорта + метрики. Обновить статус.
- [ ] **D5.** SECURITY.md: исправить ложную аттестацию про env-переменные (A4) — приоритетно, это security-отчёт.

<a name="E"></a>
### E. Роадмап фич (remote/SSH)

- [ ] **E1 (Low).** Retry с backoff и прозрачный reconnect для SSH-команд (REMOTE_TROUBLESHOOTING #8).
- [ ] **E2 (Low).** SSH tunnel для PostgreSQL/Redis (REMOTE_TROUBLESHOOTING #2) — либо вместо реализации удалить ключи конфига (A5).
- [ ] **E3 (Medium).** Jump host / bastion (paramiko proxy channel, REMOTE_TROUBLESHOOTING #5).
- [ ] **E4.** Multi-host для API-плагинов (k8s через SSH + `kubectl`, PostgreSQL через туннель) — требует отдельной оценки объёма.
- [ ] **E5 (High).** Переход на `asyncssh` вместо `run_in_executor` (REMOTE_TROUBLESHOOTING #7) — не рекомендуется в ближайшую итерацию.

<a name="F"></a>
### F. Ревизия прежних пунктов «Recommended Next Steps»

- ✅ 1–4 (SSH auth, async-обработчик, health-check tool, graceful shutdown) — отмечены закрытыми; **но по graceful shutdown см. A2 — реализация дефектная.**
- ✅ 5 (расширение корреляций) — расширено в Phase 3 (+4) и P0 (+3).
- ✅ 9 (integration-тесты) — Phase 1 (`tests/integration/` + `tests/docker-compose.test.yml`).
- ✅ 10 (nginx stub_status) — Phase 3 (`nginx_stub_status`).
- ✅ 12 (audit logging) — Phase 1 (`audit.py` + интеграция в `_make_handler`).
- 🟡 6 (тесты плагинов) — частично; непокрытые области вынесены в B1/B2.
- 🟡 11 (больше примеров в README) — частично (примеры multi-host/hosts добавлены).
- ⬜ 7 (документировать SSL mode) — значения перечислены только в `settings.yaml` (комментарий) и README-примере; отдельного раздела «SSL mode» нет.
- ⬜ 8 (clarify docker prune) — README (EN+RU) и `docs/skills/containers.md` говорят «Remove stopped containers», тогда как фактическая семантика — dry-run + явный `confirm` (`plugins/docker/__init__.py:89`); уточнить формулировки и поведение.
- ❌ 13 (аутентификация/авторизация) — отсутствует полностью: в коде нет ни API-key, ни токенов (строка `api_key` встречается только в списке ключей для редакции аудита, `audit.py:23`).

<a name="G"></a>
### G. Предлагаемый порядок работ (волны)

- [ ] **Волна 1 — правда в доках:** D1, D4, D5, C1 (доки и security-отчёт обещают несуществующее).
- [ ] **Волна 2 — быстрые баги:** A1, A2, A6, A5.
- [ ] **Волна 3 — секьюрити-контур:** A4 (+ C4), A3 (развилка a/b), A7, A9, A10.
- [ ] **Волна 4 — качество:** B1–B7, C2, C3, C5.
- [ ] **Волна 5 — рефакторинг и фичи:** A8, E1, E2.

После каждой волны прогонять гейты: `ruff check`, `ruff format --check`, `mypy`, `bandit`, `pytest`, валидация YAML, баланс code-fence в `*.md`.

