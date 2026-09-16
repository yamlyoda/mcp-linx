# TODO — Architecture Review & Findings

> Карта репо и протокол работы: [`AGENTS.md`](./AGENTS.md) (читать первым).
> Навигация по докам: [`docs/INDEX.md`](./docs/INDEX.md).

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

- [x] **A1 (P0, FIXED 2026-09-16). `mcp-linx` (console script) не запускал сервер.**
  - Было: `pyproject [project.scripts] mcp-linx = "mcp_linx.main:main"`, а `main` — `async def` → `<coroutine object main>`, `RuntimeWarning: coroutine never awaited`, `exit_code=1`; плюс не было `__main__.py` (`python -m mcp_linx` падал), а `__init__.py` затенял submodule функцией.
  - Стало: sync `def main() -> None: asyncio.run(_main_async())` + новый `src/mcp_linx/__main__.py`; работают `mcp-linx`, `python -m mcp_linx`, `python -m mcp_linx.main`. Тест: `test_entrypoint.py::test_main_is_sync_entrypoint` + `test_package_main_module_exists`.
- [x] **A2 (P0, FIXED 2026-09-16). Graceful shutdown был no-op и глотал SIGTERM/SIGINT.**
  - Было: `plugin_manager_ref` никогда не заполнялся, а `add_signal_handler` переопределял дефолтное завершение → `docker stop` висел 10 с до SIGKILL.
  - Стало: `_main_async()` ставит `stop_event` по сигналу и отменяет `server_task`; cleanup (`destroy_all` + `close_all`) выполняется в `finally` через `agent_loop.shutdown()`. Тест: `test_sigterm_triggers_shutdown` (эмуляция хендлера → задача отменена).

- [ ] **A3 (P1). `allowed_hosts` — защита заявлена, но не работает; включение сломает multi-host.**
  - README (EN+RU, Security) обещает «Host validation: whitelist of allowed_hosts»; фактически `SecurityGuard.validate_host()` (`security.py:179`) **не вызывается в `src/`** — только из `tests/unit/test_security.py`.
  - Дефолты расходятся: `security.py` → `["localhost"]`; 6 плагинов → `["localhost","127.0.0.1"]`; `settings.yaml` → 2 записи.
  - Если включить «как есть» — сломается multi-host: `web-1` / `10.130.0.23` не в whitelist.
  - Развилка: (a) удалить метод и убрать обещание из README/SECURITY.md, либо (b) реализовать с моделью «`hosts:` = доверенные SSH-таргеты, `allowed_hosts` = разрешённые probe-цели» и вызывать при валидации входных параметров. Effort: 1–3 ч.

- [ ] **A4 (P0). Секреты из env не реализованы, хотя обещано — в том числе в security-отчёте.**
  - Env читается только через `pydantic_settings.BaseSettings` для настроек сервера (`main.py:29-37`) и **не покрывает** креды плагинов: подстановки `${VAR}` в YAML нет, `os.environ`/`getenv` в коде — **0** вхождений. Секрет задаётся только plaintext в `config/settings.yaml`.
  - Обещано в: `settings.yaml` (`# из env: POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `PROMETHEUS_TOKEN`, `LOKI_TOKEN`), `docker-compose.yml` (`# LINX_SSH_PASSWORD: ${LINX_SSH_PASSWORD}` — код эту переменную не читает, см. A10), README (`password: null  # prefer env / key auth`), **`SECURITY.md:187/249`** («No hardcoded secrets — Passwords from config/env», «`config/settings.yaml` | ✅ Clean | Passwords from env»).
  - Fix: раскрытие `${VAR}` / `${VAR:-default}` при загрузке конфига + тесты (нет переменной / default / кавычки), синхронизировать доки. Effort: ~2 ч.

- [x] **A5 (P2, FIXED 2026-09-16, docs). `postgres.ssh.tunnel_host` / `tunnel_port` — ключи-заглушки.**
  - Удалены из `settings.yaml`, добавлен NOTE со ссылкой на E2; PG/Redis ходят напрямую, задавать их бессмысленно.
  - Остаток: `tunnel_host` ещё упоминается в `REMOTE_TROUBLESHOOTING.md` как план (#2) — это корректно (план, не обещание).

- [x] **A6 (P1, FIXED 2026-09-16, docs). Дефолтный audit-лог неписуем в контейнере.**
  - Код (`AuditLogger.log_call`) уже деградирует в stderr-warn; дефолт менять не стали (хост-запускам путь подходит); в `settings.yaml` добавлен комментарий: смонтировать том либо задать свой путь.

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

- [x] **B10 (FIXED 2026-09-16). CI `docker-build` падал на Trivy.**
  - Тройной fix (проверен локально `trivy image mcp-linx:ci --severity HIGH,CRITICAL --ignore-unfixed` → **Total: 0, Exit: 0**):
    1. **ci.yml**: `aquasecurity/trivy-action@0.24.0` → `@v0.36.0` (ref без `v` не существует) + `ignore-unfixed: true` → из 76 HIGH/CRITICAL осталось только реально патчащиеся.
    2. **Dockerfile (python-слой)**: `setuptools==84.0.0` (max на PyPI; 84.1.0 не существует) + `wheel>=0.46.2` — закрывают CVE-2026-24049 (wheel) и CVE-2026-23949 (jaraco.context через setuptools). Удалять нельзя: `kubernetes` держит `setuptools` как transitive.
    3. **Dockerfile (apt-слой)**: `apt-get install --only-upgrade gzip libpcre2-8-0 libsqlite3-0` — закрывает 5 Debian HIGH (CVE-2026-41992/86145/89161/11822/11824) из базового `python:3.11-slim`; security/updates-суиты уже есть в deb822 `debian.sources`, кастомные `.list` не нужны.
  - Полный per-CVE лист — в артефакте `trivy-results` (json).
  - B9 (SHA-пиннинг `FROM` + third-party-action) остаётся open — follow-up.

<a name="C"></a>
### C. Упаковка и гигиена репозитория

- [x] **C1 (FIXED 2026-09-16, частично). Метаданные пакета.**
  - `pyproject authors` → `mcp-linx team` (убран плейсхолдер `mcp-linx@example.com`). Остаток: нет файла `LICENSE` (нужен выбор лицензии), `Development Status :: 3 - Alpha`, нет `py.typed`.
- [x] **C2. `CHANGELOG.md` создан (FIXED 2026-09-15)** — исторические фазовые логи + вехи перенесены туда; `TODO.md` сокращён до живого бэклога + TOC.
- [ ] **C3. Нет `py.typed`** (PEP 561) при mypy strict и типизированном публичном API.
- [ ] **C4. Нет `.env.example`**, хотя `pydantic-settings` читает `.env` (`main.py:31`, `env_file=".env"`) и `.gitignore` разрешает `!.env.example`. Задокументировать фактически поддерживаемые имена: `CONFIG_PATH`, `LOG_LEVEL`, `MCP_SERVER_NAME`, `MCP_SERVER_VERSION`, `AGENT_LOOP` (+ `PLUGINS`, если починить — A10); связано с A4.
- [ ] **C5. Метаданные-заглушки:** `authors = mcp-linx <mcp-linx@example.com>`; нет `[project.urls]` (Homepage/Repository/Issues).
- [ ] **C6. `HARNESS_ANALYSIS.md` лежит в корне** — внутренний анализ, тогда как README ведёт список документации в `docs/`. Переместить или оставить осознанно.
- [ ] **C7.** `diagnosis_state.md` — корректно в `.gitignore` («креды, kept local only»), **не трогать**.

<a name="D"></a>
### D. Документация (следует за фиксами кода)

- [x] **D1 (FIXED 2026-09-16, docs). README обещал `allowed_hosts`-whitelist как границу защиты.**
  - README.md/README.ru.md переписаны: `validate_host()` существует и unit-tested, но не встроен в пути вызовов (A3) — как enforcement не рассматривать. Сам A3 остаётся открытым (развилка wire-up vs убрать).
- [ ] **D2.** Добавить раздел про env-переменные (реальные имена полей `Settings`, см. A10) и `${VAR}` (A4), audit-лог и путь к нему (A6), корректное завершение по SIGTERM / `docker stop` (A2). Сейчас в `docs/DEVELOPMENT.md` про env **нет ничего**.
- [ ] **D3.** README Configuration: пометить/убрать `tunnel_host` (A5 ✅ — ключи удалены из `settings.yaml`, в README их и не было) и секцию `logging:` (A7); задокументировать `rate_limit_*` (A9).
- [x] **D4 (FIXED 2026-09-16, docs). REMOTE_TROUBLESHOOTING #6 помечен TODO при частичной реализации.**
  - Раздел #6 → 🟡 PARTIAL (keepalive + dead-reconnect done, retry/metrics → E1); таблица приоритетов и Quick Wins обновлены.
- [x] **D5 (FIXED 2026-09-16, docs). SECURITY.md аттестовал секреты «from config/env».**
  - Три места исправлены на правду: секреты — plaintext в `settings.yaml`, `${VAR}` не реализован (→ A4).

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

