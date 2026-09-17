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

- [x] **A3 (P1, FIXED 2026-09-16, вариант b — wire-up). `allowed_hosts` — защита заявлена и теперь работает.**
  - Было: `SecurityGuard.validate_host()` (`security.py`) не вызывался в `src/` (только из тестов); README обещал whitelist как границу защиты.
  - Стало: вызов добавлен в `_run_command`/`_run` **всех 3 плагинов с параметром `host`** (`linux/__init__.py:121`, `nginx/__init__.py:104`, `systemd/__init__.py:97`) — проверка идёт до `_resolve_adapter`, т.е. до обращения к сети.
  - Семантика зафиксирована в `settings.yaml:44-47`: `hosts:` = доверенные SSH-таргеты, `allowed_hosts` = разрешённые probe-цели; пустой `[]` = без ограничений (свободный multi-host).
  - Тесты: `test_entrypoint.py::TestAllowedHosts` — хост вне whitelist блокируется до резолва адаптера; пустой whitelist пропускает.

- [x] **A4 (P0, FIXED 2026-09-16). `${VAR}`-подстановка в YAML реализована — секреты не обязательно держать plaintext.**
  - Env читается только через `pydantic_settings.BaseSettings` для настроек сервера (`main.py:31-43`) и **не покрывает** креды плагинов: подстановки `${VAR}` в YAML нет, `os.environ`/`getenv` в коде — **0** вхождений. Секрет задаётся только plaintext в `config/settings.yaml`.
  - Обещано в: `settings.yaml` (`# из env: POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `PROMETHEUS_TOKEN`, `LOKI_TOKEN`), `docker-compose.yml` (`# LINX_SSH_PASSWORD: ${LINX_SSH_PASSWORD}` — код эту переменную не читает, см. A10), README (`password: null  # prefer env / key auth`), **`SECURITY.md:187/249`** («No hardcoded secrets — Passwords from config/env», «`config/settings.yaml` | ✅ Clean | Passwords from env»).
  - Стало: `main.py::_expand_env_vars` + `load_config` раскрывают `${VAR}` / `${VAR:-default}` при загрузке YAML; отсутствие переменной без default → fail-open в raw-значение + WARNING (загрузка не падает).
  - Тесты: `test_entrypoint.py::TestEnvSubstitution` (4) — env-подстановка, default при отсутствии, fail-open с warning, реальный `config/settings.yaml` грузится без env.
  - Доки синхронизированы: `SECURITY.md` (D5), комментарии в `settings.yaml`. Остаток `.env.example` закрыт: C4 ✅ (2026-09-17).

- [x] **A5 (P2, FIXED 2026-09-16, docs). `postgres.ssh.tunnel_host` / `tunnel_port` — ключи-заглушки.**
  - Удалены из `settings.yaml`, добавлен NOTE со ссылкой на E2; PG/Redis ходят напрямую, задавать их бессмысленно.
  - Остаток: `tunnel_host` ещё упоминается в `REMOTE_TROUBLESHOOTING.md` как план (#2) — это корректно (план, не обещание).

- [x] **A6 (P1, FIXED 2026-09-16, docs). Дефолтный audit-лог неписуем в контейнере.**
  - Код (`AuditLogger.log_call`) уже деградирует в stderr-warn; дефолт менять не стали (хост-запускам путь подходит); в `settings.yaml` добавлен комментарий: смонтировать том либо задать свой путь.

- [x] **A7 (P2, FIXED 2026-09-17, выбранная опция — чистка). Секция `logging:` мертва; `structlog` не использовался.**
  - Было: нет `logging.config.dictConfig`; `structlog` импортировался **0** раз, но стоял в `dependencies`; `environment.mode`/`debug` и `telemetry.log_level` код не читал. Единственное чтение уровня — `Settings.log_level` (env `LOG_LEVEL`) → `basicConfig` (`main.py:49-53`).
  - Стало (объём выбран пользователем — удаление): секция `logging:` **удалена** из `settings.yaml` (на её месте NOTE-указатель), `structlog>=24.0.0` **убран** из `pyproject.toml` (образ худее; в локальном venv пакет остаётся транзитивным — код его не импортирует). Проверено: `yaml.safe_load` → ключа `logging` нет, `import mcp_linx.main` работает.
  - Осталось осознанно (резервы, помечены inline-NOTE «A7: НЕ читается»): `environment.mode`/`debug` (`settings.yaml:7-9`) и `telemetry.log_level` (`settings.yaml:52`). Живые ключи секции — `telemetry.audit_log` / `audit_log_file` (`audit.py:74-80`) — не тронуты.

- [x] **A8 (P1, FIXED 2026-09-17. `SSHAdapter` — тонкая обёртка над `SSHConnectionPool` + `exec_command_sync`, +6 unit-тестов; прежний +11 был ошибкой сравнения unit/full). Дублирование SSH-логики: `SSHAdapter` vs `SSHConnectionPool`.**
  - `SSHAdapter` — копия host-key policy / known_hosts / connect / exec, но **без** `connect_timeout` и без `set_keepalive` (в пуле оба есть) и без переиспользования соединений. Два код-пути → расхождение поведения.
  - Стало: `SSHAdapter.connect()` = `pool.get(config)` (единый код-путь: policy/known_hosts/connect_kwargs/timeout=10/keepalive 30s в `ssh_pool._connect`); `execute_command` = `exec_command_sync` из `ssh_pool`; `ping()` = `execute_command("echo OK", 5)` по returncode (как в `RemoteHostAdapter`); `disconnect()` = `pool.close_all()` (свой пул на адаптер — изоляция плагинов); удалены `_connect_sync`/`_execute_command_sync` и мёртвый `assert` (nosec B101). Бонус: унаследованы `connect_timeout` и `set_keepalive`, которых у старого `SSHAdapter` не было.
  - Тесты: `tests/unit/test_ssh_policy.py` (+6 unit, исправлено с +11): reuse/connect_timeout=10/keepalive(30)/reconnect мёртвого, изоляция `disconnect`, ping по exit-code, ошибки соединения, `execute_and_parse`. Полный набор: **215 passed, 2 skipped**; ruff/format/mypy/bandit зелёные.

- [x] **A9 (P2, FIXED 2026-09-17. `apply_timeout` удалён, rate-limit ✅; wire-up `command_timeout_seconds` в дефолты плагинов, +15 тестов). Заглушки и мёртвый/недоступный API.**
  - ✅ `SecurityGuard.apply_timeout()` **удалён** (2026-09-17): был заглушкой (`timeout = timeout or self._command_timeout; return func` — без обёртки), не вызывался нигде (0 ссылок в `src/`, `tests/`, docs). Таймауты реально применяются в `adapters/base.py:102` (`asyncio.wait_for`) и через paramiko `timeout=`.
  - ❌ **Опровергнуто** (2026-09-17): прежний тезис «аннотации `# nosec` бессмысленны — удалить» **неверен**. Probe (копия файла без аннотаций → `bandit`): удаление `# nosec B507` (×4) даёт 4×High `B507` (`ssh.py:38/43`, `ssh_pool.py:66/71`), удаление `# nosec B601` на `ssh.py:114` — Medium `B601` (отчёт на строке 112, `ping()`), удаление `# nosec B110`/`B101` — тоже реальные находки. Все аннотации load-bearing ⇒ **ничего не удалять**; 4 WARNING «nosec encountered (B507), but no failed test» — ложное срабатывание эвристики bandit на multi-line вызовах.
  - 🔎 Новая находка (2026-09-17): после удаления `apply_timeout` атрибут `SecurityGuard._command_timeout` (`security.py:95`) нигде не читается → ключ `security.command_timeout_seconds` на таймауты НЕ влияет (они задаются per-tool в плагинах). РЕШЕНО (2026-09-17): ключ проведён в дефолты плагинов — см. следующий пункт.
  - [wire-up A9, 2026-09-17] `security.command_timeout_seconds` больше не мёртвый: `SecurityGuard.command_timeout` (property, `security.py:98`) → `DiagnosticPlugin.command_timeout` (`plugins/base.py:54`, raises RuntimeError без `initialize`) → в `_run*` шести плагинов (`linux`, `nginx`, `systemd`, `kubernetes`, `netdiag`, `redis`) `if timeout is None: timeout = self.command_timeout` перед `adapter.execute_command`. Явный per-tool timeout сохраняется и перекрывает конфиг.
  - Тесты: `tests/unit/test_command_timeout.py` (+15) — 6 плагинов × [дефолт из конфига / override], tool-путь `linux_disk` (без явного timeout), дефолт guard = 30, RuntimeError без init. Docs: `settings.yaml:35-38`, README / README.ru / `docs/ARCHITECTURE.md` (инлайн-комментарий ключа).
  - `rate_limit_max_calls` / `rate_limit_window_seconds` ✅ (2026-09-16): задокументированы в `settings.yaml:42-43`; реализация жива (`ratelimit.py` → `agent_loop._make_handler`).

- [x] **A10 (P2, FIXED 2026-09-17, выбранная опция — чистка). Объявленные env-переменные и настройки не подключены.**
  - ✅ `Settings.plugins` (env `PLUGINS`) **удалено**: поле не читалось нигде и вводило в заблуждение (дефолт «4 плагина» против фактических 10). Состав плагинов определяет только `config/settings.yaml::plugins.enabled` (`PluginManager.load_plugins()`).
  - Проверено: в `Settings.model_fields` осталось **5** полей (`mcp_server_name`, `mcp_server_version`, `config_path`, `log_level`, `agent_loop`); env `PLUGINS` игнорируется и не ломает старт при `extra='forbid'`.
  - `env_prefix` **сознательно не вводится** (выбранная опция): README / `.env.example` / `docker-compose.yml` используют фактические имена (`CONFIG_PATH`, `MCP_SERVER_NAME`, `MCP_SERVER_VERSION`, `LOG_LEVEL`, `AGENT_LOOP`), `LINX_*` в compose помечены как НЕ работающие. Комментарий над `Settings` обновлён (`main.py:31-35`).
  - Docs: `.env.example` (C4 ✅), README / README.ru, `docker-compose.yml`.

<a name="B"></a>
### B. Тесты и CI

- [x] **B1 (FIXED 2026-09-17). Тесты ядра оркестрации:** `test_agent_loop_handler.py` — metadata/context, rate-limit, audit finally, ошибки и setup; `test_entrypoint.py` — выбор loop и отсутствующий конфиг, ранее добавлены env и shutdown. Отказы rate-limit сейчас не аудируются (return до try/finally); тест фиксирует текущее поведение.
- [x] **B2 (FIXED 2026-09-17). Тесты адаптеров/плагинов:** `test_adapters_docker.py` (19) и `test_plugin_core.py` (29) — PostgreSQL, Redis, Kubernetes, Prometheus, Loki: конфиг, lifecycle, health/error, SQL/команды/URL; без сети, через фейки.
- [x] **B3 (FIXED 2026-09-17). Coverage:** `pytest-cov` добавлен в dev; baseline unit line+branch **62.27%**, CI `--cov-fail-under=60`; **204 unit passed**.
- [x] **B4 (FIXED 2026-09-17). Integration-job:** `pytest -m integration -q`, Docker/Compose preflight и установка `redis-tools`. Локально **5 passed, 2 skipped** (нет redis-cli); полный запуск на GitHub ещё не проверен.
- [x] **B5 (FIXED 2026-09-17). Discovery:** точные `== 10` / `== 56` в CI и `test_discovery.py`.
- [x] **B6 (FIXED 2026-09-17). CI matrix:** Python 3.11/3.12/3.13; локальный прогон только 3.11, остальные — при запуске CI.
- [x] **B7 (FIXED 2026-09-17). SSH policy:** `test_ssh_policy.py` — дефолт RejectPolicy, opt-in политики, known_hosts, параметры подключения и disconnect.

- [x] **B8. CI падал на резолве `aquasecurity/trivy-action@0.24.0`** — у экшена все теги идут с префиксом `v`, ref без префикса не существует («Unable to resolve action… unable to find version 0.24.0»). ✅ FIXED 2026-09-15 → `@v0.36.0` + синхронизирован `SECURITY.md:211`.
- [x] **B9 (FIXED 2026-09-17). GitHub Actions закреплены по commit SHA**, добавлен `.github/dependabot.yml` (weekly actions + pip). Пиннинг базового Docker FROM по digest не входит в эту правку и остаётся отдельным follow-up.

- [x] **B10 (FIXED 2026-09-16). CI `docker-build` падал на Trivy.**
  - Тройной fix (проверен локально `trivy image mcp-linx:ci --severity HIGH,CRITICAL --ignore-unfixed` → **Total: 0, Exit: 0**):
    1. **ci.yml**: `aquasecurity/trivy-action@0.24.0` → `@v0.36.0` (ref без `v` не существует) + `ignore-unfixed: true` → из 76 HIGH/CRITICAL осталось только реально патчащиеся.
    2. **Dockerfile (python-слой)**: `setuptools==84.0.0` (max на PyPI; 84.1.0 не существует) + `wheel>=0.46.2` — закрывают CVE-2026-24049 (wheel) и CVE-2026-23949 (jaraco.context через setuptools). Удалять нельзя: `kubernetes` держит `setuptools` как transitive.
    3. **Dockerfile (apt-слой)**: `apt-get install --only-upgrade gzip libpcre2-8-0 libsqlite3-0` — закрывает 5 Debian HIGH (CVE-2026-41992/86145/89161/11822/11824) из базового `python:3.11-slim`; security/updates-суиты уже есть в deb822 `debian.sources`, кастомные `.list` не нужны.
  - Полный per-CVE лист — в артефакте `trivy-results` (json).
  - B9 actions SHA закрыт 2026-09-17; пиннинг Docker `FROM` по digest остаётся отдельным follow-up.

<a name="C"></a>
### C. Упаковка и гигиена репозитория

- [x] **C1 (FIXED 2026-09-16, частично). Метаданные пакета.**
  - `pyproject authors` → `mcp-linx team` (убран плейсхолдер `mcp-linx@example.com`). Остаток: нет файла `LICENSE` (нужен выбор лицензии), `Development Status :: 3 - Alpha`. `py.typed` добавлен 2026-09-17 (C3 ✅).
- [x] **C2. `CHANGELOG.md` создан (FIXED 2026-09-15)** — исторические фазовые логи + вехи перенесены туда; `TODO.md` сокращён до живого бэклога + TOC.
- [x] **C3 (FIXED 2026-09-17). PEP 561:** добавлен `src/mcp_linx/py.typed`; присутствие проверено в wheel, sdist и Docker-образе.
- [x] **C4 (FIXED 2026-09-17, docs). Нет `.env.example`** — создан, хотя `pydantic-settings` читает `.env` (`main.py:36`, `env_file=".env"`), а `.gitignore` разрешает `!.env.example`.
  - Задокументированы фактические имена: `MCP_SERVER_NAME`, `MCP_SERVER_VERSION`, `CONFIG_PATH`, `LOG_LEVEL`, `AGENT_LOOP` (+ `PLUGINS` не поддерживается: поле удалено в A10).
  - Отдельный блок — секреты через `${VAR}` в `settings.yaml` (A4): `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `PROMETHEUS_TOKEN`, `LOKI_TOKEN` (с файлами:строками) + fail-open предупреждение.
  - Плюс `SSH_KEY_DIR` (интерполяция docker-compose, не Python). Указатель на файл добавлен в README / README.ru (Configuration).
  - Связано с A4 ✅; остаток env-документации — D2 (секция в `docs/DEVELOPMENT.md`).
- [x] **C5 (FIXED 2026-09-17). `[project.urls]`:** Homepage/Repository/Issues добавлены в `pyproject.toml`, проверены в метаданных собранного пакета.
- [ ] **C6. `HARNESS_ANALYSIS.md` лежит в корне** — внутренний анализ, тогда как README ведёт список документации в `docs/`. Переместить или оставить осознанно.
- [ ] **C7.** `diagnosis_state.md` — корректно в `.gitignore` («креды, kept local only»), **не трогать**.

<a name="D"></a>
### D. Документация (следует за фиксами кода)

- [x] **D1 (FIXED 2026-09-16, docs). README обещал `allowed_hosts`-whitelist как границу защиты.**
  - README.md/README.ru.md переписаны: `validate_host()` не только unit-tested, но и встроен в пути вызовов (A3 ✅, 2026-09-16) — формулировка «whitelist» снова корректна, уточнить семантику (`hosts:` = доверенные таргеты, `allowed_hosts` = probe-цели).
- [x] **D2 (FIXED 2026-09-17, docs).** В DEVELOPMENT добавлены пять env-полей Settings, приоритет окружения, ограничения `.env`, `${VAR}` и fail-open/YAML quoting, передача секретов Docker, audit-путь и SIGTERM/`docker stop`.
- [x] **D3 (FIXED 2026-09-17, docs).** README EN/RU: рабочие `${VAR:-}` для паролей, rate-limit и allowed_hosts, фактическая валидация params/host, dry-run prune, актуальные пути и отсутствие LICENSE. Секция logging не предлагается; DEBUG задаётся через LOG_LEVEL. SECURITY и .env.example согласованы с A4.
- [x] **D4 (FIXED 2026-09-16, docs). REMOTE_TROUBLESHOOTING #6 помечен TODO при частичной реализации.**
  - Раздел #6 → 🟡 PARTIAL (keepalive + dead-reconnect done, retry/metrics → E1); таблица приоритетов и Quick Wins обновлены.
- [x] **D5 (FIXED 2026-09-16, docs). SECURITY.md аттестовал секреты «from config/env».**
  - Статус на 2026-09-17: `${VAR}` / `${VAR:-default}` реализованы (A4).
    SECURITY.md синхронизирован с фактической подстановкой из окружения процесса;
    `.env` сервера не предназначен для секретов плагинов.
- [x] **D6 (FIXED 2026-09-17, сверка docs/code).** README EN/RU, DEVELOPMENT и ARCHITECTURE уточняют: `plugins.enabled` ограничивает инициализацию, не регистрацию tools/health-check; readonly — проверка команд, не общий запрет Docker API; rate-limit — только плагинные обработчики. Исправлены настройки запуска (env, не YAML), статус streaming, путь создания плагина и docstring `prune_containers`. Поведение кода не менялось. Полный `.venv/bin/python -m pytest -q`: 215 passed, 2 skipped, PYTEST_EXIT=0 (обёртка терминала сообщает ошибку закрытия); ruff/format изменённого Python-файла и mypy src — OK.


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
- ✅ 8 (clarify docker prune, 2026-09-17) — README EN/RU и `docs/skills/containers.md`: dry-run по умолчанию, удаление только при `execute=true` и `confirm=true`.
- ❌ 13 (аутентификация/авторизация) — отсутствует полностью: в коде нет ни API-key, ни токенов (строка `api_key` встречается только в списке ключей для редакции аудита, `audit.py:23`).

<a name="G"></a>
### G. Предлагаемый порядок работ (волны)

- [x] **Волна 1 — правда в доках (2026-09-16):** D1 ✅, D4 ✅, D5 ✅, C1 🟡 (authors ✅; LICENSE/`py.typed` открыты) — остаток D2/D3.
- [x] **Волна 2 — быстрые баги (2026-09-16):** A1 ✅, A2 ✅, A5 ✅, A6 ✅ (гейт 114 → 120 passed).
- [x] **Волна 3 — секьюрити-контур (✅ 2026-09-17, закрыта):** A4 ✅ (`${VAR}`-подстановка + 4 теста), A3 ✅ (wire-up `validate_host` + 2 теста), A9 ✅ (`apply_timeout` удалён; rate-limit ✅; `command_timeout_seconds` проведён в дефолты плагинов, +15 тестов), C4 ✅ (`.env.example` + указатель в README), A7 ✅ (секция `logging:` + `structlog` удалены), A10 ✅ (`Settings.plugins` удалено) — остаток env-доков: D2.
- [x] **Волна 4 — качество (2026-09-17):** B1–B7, B9 (actions), C2, C3, C5. Unit: 204 passed, coverage 62.27%; integration: 5 passed / 2 skipped (локально нет redis-cli). Ruff/mypy/bandit зелёные; wheel/sdist, Docker build и MCP smoke — OK. Матрица 3.12/3.13 и полный integration — ожидают CI.
- [ ] **Волна 5 — рефакторинг и фичи:** A8 ✅ (2026-09-17, +6 unit-тестов: 204 → 210; полный набор 215 passed / 2 skipped включает 5 integration); E1, E2 — открыты. Исправлен прежний ошибочный прирост +11 и преждевременное закрытие волны.

После каждой волны прогонять гейты: `ruff check`, `ruff format --check`, `mypy`, `bandit`, `pytest`, валидация YAML, баланс code-fence в `*.md`.

