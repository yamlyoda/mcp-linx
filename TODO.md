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
  - Семантика зафиксирована в `settings.yaml:44-46`: `hosts:` = доверенные SSH-таргеты, `allowed_hosts` = разрешённые probe-цели; пустой `[]` = без ограничений (свободный multi-host).
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
  - Осталось осознанно (резервы, помечены inline-NOTE «A7: НЕ читается»): `environment.mode`/`debug` и `telemetry.log_level` — **удалены в волне 6 (2026-09-18, A11)** как мёртвые. Живые ключи секции — `telemetry.audit_log` / `audit_log_file` (`audit.py:74-80`) — не тронуты.

- [x] **A8 (P1, FIXED 2026-09-17. `SSHAdapter` — тонкая обёртка над `SSHConnectionPool` + `exec_command_sync`, +6 unit-тестов; прежний +11 был ошибкой сравнения unit/full). Дублирование SSH-логики: `SSHAdapter` vs `SSHConnectionPool`.**
  - `SSHAdapter` — копия host-key policy / known_hosts / connect / exec, но **без** `connect_timeout` и без `set_keepalive` (в пуле оба есть) и без переиспользования соединений. Два код-пути → расхождение поведения.
  - Стало: `SSHAdapter.connect()` = `pool.get(config)` (единый код-путь: policy/known_hosts/connect_kwargs/timeout=10/keepalive 30s в `ssh_pool._connect`); `execute_command` = `exec_command_sync` из `ssh_pool`; `ping()` = `execute_command("echo OK", 5)` по returncode (как в `RemoteHostAdapter`); `disconnect()` = `pool.close_all()` (свой пул на адаптер — изоляция плагинов); удалены `_connect_sync`/`_execute_command_sync` и мёртвый `assert` (nosec B101). Бонус: унаследованы `connect_timeout` и `set_keepalive`, которых у старого `SSHAdapter` не было.
  - Тесты: `tests/unit/test_ssh_policy.py` (+6 unit, исправлено с +11): reuse/connect_timeout=10/keepalive(30)/reconnect мёртвого, изоляция `disconnect`, ping по exit-code, ошибки соединения, `execute_and_parse`. Полный набор: **215 passed, 2 skipped**; ruff/format/mypy/bandit зелёные.

- [x] **A9 (P2, FIXED 2026-09-17. `apply_timeout` удалён, rate-limit ✅; wire-up `command_timeout_seconds` в дефолты плагинов, +15 тестов). Заглушки и мёртвый/недоступный API.**
  - ✅ `SecurityGuard.apply_timeout()` **удалён** (2026-09-17): был заглушкой (`timeout = timeout or self._command_timeout; return func` — без обёртки), не вызывался нигде (0 ссылок в `src/`, `tests/`, docs). Таймауты реально применяются в `adapters/base.py:102` (`asyncio.wait_for`) и через paramiko `timeout=`.
  - ❌ **Опровергнуто** (2026-09-17): прежний тезис «аннотации `# nosec` бессмысленны — удалить» **неверен**. Probe (копия файла без аннотаций → `bandit`): удаление `# nosec B507` (×4) даёт 4×High `B507` (`ssh.py:38/43`, `ssh_pool.py:66/71`), удаление `# nosec B601` на `ssh.py:114` — Medium `B601` (отчёт на строке 112, `ping()`), удаление `# nosec B110`/`B101` — тоже реальные находки. Все аннотации load-bearing ⇒ **ничего не удалять**; 4 WARNING «nosec encountered (B507), but no failed test» — ложное срабатывание эвристики bandit на multi-line вызовах.
  - 🔎 Новая находка (2026-09-17): после удаления `apply_timeout` атрибут `SecurityGuard._command_timeout` (`security.py:95`) нигде не читается → ключ `security.command_timeout_seconds` на таймауты НЕ влияет (они задаются per-tool в плагинах). РЕШЕНО (2026-09-17): ключ проведён в дефолты плагинов — см. следующий пункт.
  - [wire-up A9, 2026-09-17] `security.command_timeout_seconds` больше не мёртвый: `SecurityGuard.command_timeout` (property, `security.py:98`) → `DiagnosticPlugin.command_timeout` (`plugins/base.py:54`, raises RuntimeError без `initialize`) → в `_run*` шести плагинов (`linux`, `nginx`, `systemd`, `kubernetes`, `netdiag`, `redis`) `if timeout is None: timeout = self.command_timeout` перед `adapter.execute_command`. Явный per-tool timeout сохраняется и перекрывает конфиг.
  - Тесты: `tests/unit/test_command_timeout.py` (+15) — 6 плагинов × [дефолт из конфига / override], tool-путь `linux_disk` (без явного timeout), дефолт guard = 30, RuntimeError без init. Docs: `settings.yaml:31-36`, README / README.ru / `docs/ARCHITECTURE.md` (инлайн-комментарий ключа).
  - `rate_limit_max_calls` / `rate_limit_window_seconds` ✅ (2026-09-16): задокументированы в `settings.yaml:39-40`; реализация жива (`ratelimit.py` → `agent_loop._make_handler`).

- [x] **A10 (P2, FIXED 2026-09-17, выбранная опция — чистка). Объявленные env-переменные и настройки не подключены.**
  - ✅ `Settings.plugins` (env `PLUGINS`) **удалено**: поле не читалось нигде и вводило в заблуждение (дефолт «4 плагина» против фактических 10). Состав плагинов определяет только `config/settings.yaml::plugins.enabled` (`PluginManager.load_plugins()`).
  - Проверено: в `Settings.model_fields` осталось **5** полей (`mcp_server_name`, `mcp_server_version`, `config_path`, `log_level`, `agent_loop`); env `PLUGINS` игнорируется и не ломает старт при `extra='forbid'`.
  - `env_prefix` **сознательно не вводится** (выбранная опция): README / `.env.example` / `docker-compose.yml` используют фактические имена (`CONFIG_PATH`, `MCP_SERVER_NAME`, `MCP_SERVER_VERSION`, `LOG_LEVEL`, `AGENT_LOOP`), `LINX_*` в compose помечены как НЕ работающие. Комментарий над `Settings` обновлён (`main.py:31-35`).
  - Docs: `.env.example` (C4 ✅), README / README.ru, `docker-compose.yml`.

- [x] **A11 (P1, FIXED 2026-09-18, волна 6). `plugins.enabled` фильтровал только инициализацию.**
  - Было: `initialize_all()` учитывал `plugins.enabled`, а `get_tools()` и `health_check_all()` шли по всем загруженным → инструменты исключённого плагина регистрировались в MCP и падали при вызове `RuntimeError: Plugin not initialized`; на старте health-check писал ERROR.
  - Стало: `PluginManager._enabled_ids()` (None = без ограничений) + фильтр в `load_plugins()`; `get_tools()`/`health_check_all()`/`destroy_all()` работают по активному набору. Неизвестный id в `enabled` → WARNING (защита от опечатки, молча отключающей всё). Некорректная (не-dict) секция `plugins` трактуется как «все».
  - Мёртвые ключи удалены (тот же класс, что A7/A10): секция `environment:` (`mode`/`debug`), `telemetry.log_level` и **10 per-plugin `enabled: true`** — ни один не читался кодом (`PluginConfig` — просто dict). Живые `telemetry.audit_log`/`audit_log_file` не тронуты.
  - Тесты: `tests/unit/test_plugin_manager.py` (**+11**) — подмена `PLUGIN_REGISTRY` фиктивными плагинами (без инфраструктуры): subset/пусто/нет ключа/не-dict, лимиты tools и health-check, warning на неизвестный id, scope `initialize_all`/`destroy_all`, плюс тест синхронности `config/settings.yaml::plugins.enabled` ↔ реестр (ловит «потерянный» плагин).
  - Docs: `settings.yaml` (комментарий + NOTE), README EN/RU, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT.md`, AGENTS §3.

- [x] **A12 (P1, FIXED 2026-09-18, волна 9). `readonly` не покрывал некомандный write-путь (Docker prune).**
  - Было: `docker_prune` уважал только собственный `confirm`; `security.readonly: true` (дефолт) удаление не блокировал — при том, что это деструктивная операция.
  - Стало: у `SecurityGuard` появилось публичное свойство `readonly`; `DockerPlugin.initialize()` строит guard из секции `security` (как linux/nginx/systemd), а `DockerPlugin.prune_containers()` бросает `SecurityError` при `readonly: true`. Барьер стоит в методе плагина, поэтому обход проверки `confirm` в инструменте не помогает; dry-run по-прежнему разрешён.
  - Тесты: `TestDockerPruneReadonly` в `tests/unit/test_base_plugins.py` (+6): блокировка execute, разрешённый dry-run, разрешение при `readonly: false`, `SecurityError` из метода, wiring guard из конфига, дефолт guard.
  - Docs: README EN/RU и `docs/ARCHITECTURE.md` — прежняя формулировка «некомандные пути не проверяют readonly» **исправлена на фактическую**.

- [x] **A13 (P2, FIXED 2026-09-18, волна 9). Отказы rate-limit не попадали в аудит.**
  - Было: проверка лимита стояла до `try/finally` хендлера, поэтому `return` с ошибкой не проходил через `audit_logger.log_call`.
  - Стало: проверка перенесена внутрь `try`, отказ аудируется со `status="error"` и текстом причины; успешный путь не изменился.
  - Тесты: `TestHandlerRateLimit` в `tests/unit/test_agent_loop_handler.py` обновлён (было зафиксировано прежнее поведение) — теперь ожидает 2 записи аудита и `status="error"`.
  - Docs: SECURITY.md (чек-лист аудита и rate-limit).

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
- [x] **B11 (FIXED 2026-09-25). Регрессия CI из-за новых bind9 CVE и локального docs-файла.**
  - `dnsutils` transitively установил bind9 `1:9.20.27-1~deb13u2` с 21 patchable HIGH. Runtime-слой теперь обновляет `bind9-dnsutils` (`1:9.20.29-1~deb13u1`); HIGH/CRITICAL gate и secret scanning не ослаблены. Docker build OK; Trivy: 0 HIGH/CRITICAL, 0 secrets, exit 0.
  - `diagnosis_state.md` намеренно gitignored. `docs/INDEX.md` больше не заявляет числовой размер, а docs-тест не требует локальный файл в CI; проверка остальных документов и их счётчиков сохранена.

<a name="C"></a>
### C. Упаковка и гигиена репозитория

- [x] **C1 (FIXED 2026-09-18, полностью). Метаданные пакета.**
  - `pyproject authors` → `mcp-linx team` (убран плейсхолдер `mcp-linx@example.com`).
  - **`LICENSE` создан** (MIT, «mcp-linx team», 2026); метаданные переведены на PEP 639: `license = "MIT"` + `license-files = ["LICENSE"]`, устаревший classifier `License :: OSI Approved :: MIT License` удалён. `Development Status :: 3 - Alpha` задокументирован в README (EN/RU) — статус Alpha заявлен явно.
  - Проверено сборкой: `License-Expression: MIT`, `License-File: LICENSE` в METADATA; `LICENSE` присутствует в wheel и sdist. `py.typed` добавлен 2026-09-17 (C3 ✅).
- [x] **C2. `CHANGELOG.md` создан (FIXED 2026-09-15)** — исторические фазовые логи + вехи перенесены туда; `TODO.md` сокращён до живого бэклога + TOC.
- [x] **C3 (FIXED 2026-09-17). PEP 561:** добавлен `src/mcp_linx/py.typed`; присутствие проверено в wheel, sdist и Docker-образе.
- [x] **C4 (FIXED 2026-09-17, docs). Нет `.env.example`** — создан, хотя `pydantic-settings` читает `.env` (`main.py:36`, `env_file=".env"`), а `.gitignore` разрешает `!.env.example`.
  - Задокументированы фактические имена: `MCP_SERVER_NAME`, `MCP_SERVER_VERSION`, `CONFIG_PATH`, `LOG_LEVEL`, `AGENT_LOOP` (+ `PLUGINS` не поддерживается: поле удалено в A10).
  - Отдельный блок — секреты через `${VAR}` в `settings.yaml` (A4): `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `PROMETHEUS_TOKEN`, `LOKI_TOKEN` (с файлами:строками) + fail-open предупреждение.
  - Плюс `SSH_KEY_DIR` (интерполяция docker-compose, не Python). Указатель на файл добавлен в README / README.ru (Configuration).
  - Связано с A4 ✅; остаток env-документации — D2 (секция в `docs/DEVELOPMENT.md`).
- [x] **C5 (FIXED 2026-09-17). `[project.urls]`:** Homepage/Repository/Issues добавлены в `pyproject.toml`, проверены в метаданных собранного пакета.
- [x] **C6 (FIXED 2026-09-18).** `HARNESS_ANALYSIS.md` перенесён в `docs/HARNESS_ANALYSIS.md`; ссылки обновлены в `docs/INDEX.md` и `AGENTS.md`. В корне остались только README EN/RU, TODO, CHANGELOG, SECURITY, REMOTE_TROUBLESHOOTING, AGENTS, LICENSE.
- [x] **C7 (no-op, 2026-09-18).** `diagnosis_state.md` — корректно в `.gitignore` («креды, kept local only»). Проверок не требует; задача закрыта как «не трогать», чтобы не выглядела открытой.
- [x] **C8 (FIXED 2026-09-18). Docker `FROM` без digest.** Оба стейджа запинены: `python:3.11-slim@sha256:9534e5a8…`; в Dockerfile добавлен комментарий, как обновлять digest (`docker buildx imagetools inspect`). Сборка образа с пином — OK.
- [x] **C9 (FIXED 2026-09-18, поднято в волне 12). Coverage-гейт и Python 3.12.** Добавлены `tests/unit/test_adapters_local.py` (+12) и `tests/unit/test_context_compactors.py` (+12): покрытие unit **62.27% → 66.06%**, CI-гейт 60 → 65. Полный unit-набор прогнан локально на **Python 3.12** (`245 passed`) — ранее 3.12/3.13 проверялись только в CI (3.13 локально недоступен).
  - Волна 12 продолжила работу: `test_agent_loop_lifecycle.py` (+18, agent_loop 47% → 96%), `test_main_startup.py` (+5, main.py 80% → 100%), `test_observability_tools.py` (+24, loki 19% → 92%, prometheus 19% → 89%). Итог: **67.74% → 75%**, CI-гейт **65 → 72**.
- [x] **C13 (FIXED 2026-09-18, волна 12). Провалы покрытия в критичных модулях закрыты.** `harness/agent_loop.py` (47% → 96%: setup/run/shutdown, системные tools, seed контекста), `main.py` (80% → 100%: старт сервера, ветка завершения, sync entrypoint), `plugins/loki|prometheus/tools.py` (19% → 92%/89%: HTTP-успехи, HTTP-ошибки, degraded-ветки, валидация, transport-исключения). Остаются непокрытыми: `plugins/docker|kubernetes|postgres/tools.py` (28-29%), `netdiag|redis` (45%), `linux` (56%), `nginx` (68%) — кандидаты на следующую итерацию; гейт 72 допускает их текущий уровень.
- [x] **C14 (FIXED 2026-09-18, волна 13). E2/E3 сквозная проверка на реальном SSH.** `tests/integration/test_ssh_tunnel_e2e.py`: форвардинг через `SSHTunnel` проверяется по SSH-баннеру удалённого хоста, плюс выполнение команды (E1) и переиспользование соединения. Тест opt-in (env `MCP_LINX_SSH_HOST`/`_USER`/`_KEY`, опционально `_PORT`/`_REMOTE_PORT`/`_JUMP`/`_HOST_KEY_POLICY`) и скипается там, где SSH-хоста нет (в CI). Инструкция запуска — `docs/DEVELOPMENT.md`.
- [x] **C10 (FIXED 2026-09-18). `docs/INDEX.md` расходился с файлами.** Счётчики строк обновлены по факту; добавлен тест-страж `tests/unit/test_docs_index.py`, который падает при дрейфе (сообщает актуальные значения).
- [x] **C11 (FIXED 2026-09-18). Мёртвый `harness/sandbox.py` удалён.** Модуль (`Sandbox` / `LocalSandbox` / `DockerSandbox` / `RemoteSandbox`, 208 строк) не вызывался ни из `agent_loop`, ни из плагинов — только реэкспорт в `harness/__init__.py`. Удалён вместе с реэкспортом; статусы приведены к факту в `docs/HARNESS_ANALYSIS.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT.md`, README EN/RU, AGENTS §1. Изоляция команд обеспечивается моделью запуска контейнера и `SecurityGuard` (обоснование — HARNESS_ANALYSIS §3).
- [x] **C12 (FIXED 2026-09-18, решение). Компакторы контекста — осознанный резерв, не мёртвый код.** `harness/context.py` (`ContextCompactor` + 3 реализации) экспортируется и покрыт тестами, но в `agent_loop` не подключён: сервер не хранит историю диалога — её ведёт MCP-клиент. Ключи конфига для компакции **не вводим**, пока нет потребителя (иначе это были бы мёртвые ключи). Решение зафиксировано в `docs/HARNESS_ANALYSIS.md` (Фаза 4).
- [x] **C15 (FIXED 2026-09-25, волна 14). Провалы покрытия в `tools.py` плагинов закрыты.** Новые файлы: `test_docker_tools.py` (+17; docker 28% → 100%), `test_kubernetes_tools.py` (+19; k8s 29% → 92%), `test_netdiag_tools.py` (+16; netdiag 45% → 92%), `test_redis_tools.py` (+13; redis 45% → 91%). Общее unit-покрытие **76% → 85%**; **346 → 418 passed**. Следующая итерация закрыла оставшиеся `postgres/linux/nginx` tools в C16. Ловушка: `tools_mod.time.monotonic` патчить нельзя через `setattr(tools_mod.time, ...)` — это глобальный модуль, который дёргает event loop; патчить имя `time` в неймспейсе модуля (`setattr(tools_mod, "time", ...)`).
- [x] **C16 (FIXED 2026-09-25, волна 15). Покрытие PostgreSQL/Linux/Nginx tools.** Добавлены `test_postgres_tools.py`, `test_linux_tools.py`, `test_nginx_tools.py`; целевые модули выросли с **42/56/68% до 100/96/97%**. Покрыты успешные и degraded/error-ветки, валидация параметров, fallback-вывод, shell/network-парсинг и HTTP health checks. Runtime-код и MCP-контракт не менялись; пользовательская документация не требовалась.

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
- [x] **D7 (FIXED 2026-09-18, волна 9).** SECURITY.md: пункт «Authentication/authorization» переписан как осознанное проектное решение — сервер работает по stdio, граница доверия = родительский процесс, сетевого listener'а нет; перечислены ограничения развёртывания и требование реализовать auth **до** добавления HTTP/SSE или multi-tenant. Ссылка на Long-term Improvements #11 сохранена.


<a name="E"></a>
### E. Роадмап фич (remote/SSH)

- [x] **E1 (FIXED 2026-09-18).** Retry с backoff и прозрачный reconnect для SSH-команд (REMOTE_TROUBLESHOOTING #8).
  - `exec_command_with_retry` (`adapters/ssh_pool.py`): повтор только на ошибках соединения (`SSHException`/`EOFError`/`OSError`/`ConnectionError`), `pool.drop()` мёртвого соединения + переподключение. Ключи `retry_attempts` (дефолт 2; `1` = выключено) и `retry_backoff_seconds` (0.5, линейный рост) в `hosts.<имя>` и `plugins.<плагин>.ssh`. Ненулевой код возврата не ретраится.
  - Тесты: `tests/unit/test_ssh_retry.py` (+12), включая `retry_params` и `SSHConnectionPool.drop`.
- [x] **E2 (FIXED 2026-09-18).** SSH tunnel для PostgreSQL (REMOTE_TROUBLESHOOTING #2).
  - `SSHTunnel` (`adapters/ssh_pool.py`) — локальный форвард `direct-tcpip` на потоковом `ThreadingTCPServer`; `PostgresPlugin._maybe_start_tunnel()` включается при `plugins.postgres.ssh.tunnel: true` (требует `ssh.host`), подключение идёт на локальный адрес туннеля, `destroy()` останавливает туннель и закрывает пул. Redis не нуждается в туннеле (команды `redis-cli` по SSH).
  - Тесты: `tests/unit/test_ssh_tunnel.py` (+7, реальная перекачка байт через фейковый транспорт), `tests/unit/test_postgres_tunnel.py` (+6, wiring и deny/fail-fast).
  - **Сквозная проверка (C2, 2026-09-18):** `tests/integration/test_ssh_tunnel_e2e.py` — opt-in (`MCP_LINX_SSH_HOST`/`_USER`/`_KEY`), проверяет реальный форвардинг (SSH-баннер через туннель), выполнение команды и переиспользование соединения; без env-переменных скипается (в CI SSH-хоста нет). Инструкция — `docs/DEVELOPMENT.md`.
- [x] **E3 (FIXED 2026-09-18).** Jump host / bastion (paramiko proxy channel, REMOTE_TROUBLESHOOTING #5).
  - `SSHConnectionPool._connect`: при `jump_host` создаётся клиент бастиона, открывается `direct-tcpip` канал до цели (`_open_jump_channel`) и передаётся в целевой `connect(sock=...)`; `_jump_config` маппит ключи `jump_*` со наследованием `host_key_policy`/`known_hosts`; бастион хранится в `_jump_clients` и закрывается вместе с целью (`drop`/`close_all`).
  - Тесты: `tests/unit/test_ssh_jump.py` (+9): два клиента, адрес канала, наследование политики, дефолт порта, отсутствие транспорта бастиона, очистка, переиспользование.
  - Docs: README EN/RU (раздел «Jump host (bastion)»), `settings.yaml` (пример ключей), REMOTE #5.
- [x] **E4a (FIXED 2026-09-18, docs+тесты).** Multi-cluster Kubernetes. Плагин работает с одним кластером на инстанс (`kubeconfig`/`context`); для нескольких — дополнительные инстансы с отдельным `CONFIG_PATH`. Аргумента выбора кластера у `k8s_*` намеренно нет. Раздел «Kubernetes multi-cluster» в README EN/RU + пример в `settings.yaml`.
- [x] **E4b (FIXED 2026-09-18).** Multi-target PostgreSQL. `plugins.postgres.targets.<имя>` + параметр `host` у `pg_*`: свой коннект на таргет, при `ssh.tunnel: true` — свой туннель (E2), кэш соединений, закрытие в `destroy()`; неизвестный таргет → `KeyError` со списком настроенных. Тесты: `tests/unit/test_postgres_targets.py` (+11). Docs: README EN/RU (раздел «PostgreSQL multi-target»), `settings.yaml`.
- [x] **E4 (закрыт 2026-09-18)** — разбит на E4a/E4b, оба выполнены.
- [x] **E5 (⏸ WON'T DO NOW, 2026-09-18).** Переход на `asyncssh` вместо `run_in_executor`.
  - **Решение:** не делаем. Практические потребности закрыты: E1 (retry + reconnect) и E2 (туннель) реализованы поверх paramiko; `run_in_executor` не является бутылочным горлышком для диагностических команд (короткие, read-only). Миграция затронула бы весь SSH-слой (пул, туннель, retry) и потребовала бы нового цикла проверки на реальном SSH.
  - **Условие пересмотра:** высокая конкурентность SSH-вызовов (десятки параллельных сессий) или требование нативной async-отмены. До этого — задокументированный отказ, а не открытый пункт.
- [x] **E6 (FIXED 2026-09-25, волна 14). Композитные диагностические инструменты.** В `_register_system_tools` (`harness/agent_loop.py`) добавлены `diagnose_host` (linux: stats/processes/disk/memory/journalctl err) и `diagnose_web_service` (nginx_status + systemd service_status + nginx error-логи + опционально `http_check` по `url`). Под-вызовы идут параллельно через `asyncio.gather` + хелпер `_invoke_tool` (поиск по `plugin_manager.get_tools()`); недоступный плагин/tool → `status="skipped"`, не падает. Оба принимают `host` из `hosts:`-реестра. Замечание: внутренние вызовы обходят rate-limit/audit (как остальные system tools) — задокументировано в README EN/RU §Security. Тесты: `TestDiagnoseTools` в `test_agent_loop_lifecycle.py` (+7).

<a name="F"></a>
### F. Ревизия прежних пунктов «Recommended Next Steps»

- ✅ 1–4 (SSH auth, async-обработчик, health-check tool, graceful shutdown) — отмечены закрытыми; **но по graceful shutdown см. A2 — реализация дефектная.**
- ✅ 5 (расширение корреляций) — расширено в Phase 3 (+4) и P0 (+3).
- ✅ 9 (integration-тесты) — Phase 1 (`tests/integration/` + `tests/docker-compose.test.yml`).
- ✅ 10 (nginx stub_status) — Phase 3 (`nginx_stub_status`).
- ✅ 12 (audit logging) — Phase 1 (`audit.py` + интеграция в `_make_handler`).
- 🟡 6 (тесты плагинов) — частично; непокрытые области вынесены в B1/B2.
- 🟡 11 (больше примеров в README) — частично (примеры multi-host/hosts добавлены).
- ✅ 7 (документировать SSL mode, 2026-09-18) — раздел «PostgreSQL SSL modes» в README EN/RU: таблица режимов libpq, риск `prefer` (тихий откат в plaintext), рекомендация `verify-full`/`verify-ca`, способ задать CA и оговорка про туннель.
- ✅ 8 (clarify docker prune, 2026-09-17) — README EN/RU и `docs/skills/containers.md`: dry-run по умолчанию, удаление только при `execute=true` и `confirm=true`.
- ❌ 13 (аутентификация/авторизация) — по-прежнему не реализована. Решение зафиксировано в D7 и SECURITY.md: для stdio-транспорта граница доверия — родительский процесс; auth обязателен до появления HTTP/SSE или multi-tenant. В коде нет ни API-key, ни токенов (`api_key` встречается только в списке ключей для редакции аудита, `audit.py:23`).

<a name="G"></a>
### G. Предлагаемый порядок работ (волны)

- [x] **Волна 1 — правда в доках (2026-09-16):** D1 ✅, D4 ✅, D5 ✅, C1 🟡 (authors ✅; LICENSE/`py.typed` открыты) — остаток D2/D3.
- [x] **Волна 2 — быстрые баги (2026-09-16):** A1 ✅, A2 ✅, A5 ✅, A6 ✅ (гейт 114 → 120 passed).
- [x] **Волна 3 — секьюрити-контур (✅ 2026-09-17, закрыта):** A4 ✅ (`${VAR}`-подстановка + 4 теста), A3 ✅ (wire-up `validate_host` + 2 теста), A9 ✅ (`apply_timeout` удалён; rate-limit ✅; `command_timeout_seconds` проведён в дефолты плагинов, +15 тестов), C4 ✅ (`.env.example` + указатель в README), A7 ✅ (секция `logging:` + `structlog` удалены), A10 ✅ (`Settings.plugins` удалено) — остаток env-доков: D2.
- [x] **Волна 4 — качество (2026-09-17):** B1–B7, B9 (actions), C2, C3, C5. Unit: 204 passed, coverage 62.27%; integration: 5 passed / 2 skipped (локально нет redis-cli). Ruff/mypy/bandit зелёные; wheel/sdist, Docker build и MCP smoke — OK. Матрица 3.12/3.13 и полный integration — ожидают CI.
- [x] **Волна 5 — рефакторинг и фичи (✅ 2026-09-18, закрыта):** A8 ✅ (2026-09-17, +6 unit-тестов: 204 → 210), **E1 ✅** (retry/backoff + reconnect, +12), **E2 ✅** (SSH-туннель для PostgreSQL, +13). E3–E5 остаются как отдельные фичи вне волн.
- [x] **Волна 6 — корректность (2026-09-18):** A11 ✅ — `plugins.enabled` стал настоящим фильтром (load/init/tools/health/destroy), удалены мёртвые ключи (`environment:`, `telemetry.log_level`, 10× per-plugin `enabled`), +11 тестов `test_plugin_manager.py`. Runtime-поведение изменилось: исключённый плагин больше не регистрирует tools.
- [x] **Волна 7 — релиз и качество (2026-09-18):** C1 ✅ (`LICENSE` MIT + PEP 639 `license`/`license-files`, статус Alpha в README), C8 ✅ (Docker `FROM` по digest), C9 ✅ (coverage 62.27% → 66.06%, гейт 60 → 65; local Python 3.12: 245 passed).
- [x] **Волна 8 — гигиена документации (2026-09-18):** C6 ✅ (перенос `HARNESS_ANALYSIS.md`), C10 ✅ (`INDEX` счётчики + тест-страж), F#7 ✅ (раздел SSL mode), SECURITY.md → устаревшие «Critical Issues» помечены FIXED с проверкой по коду.
- [x] **Волна 9 — безопасность (2026-09-18):** A12 ✅ (`readonly` закрывает Docker-prune), A13 ✅ (отказы rate-limit аудируются), D7 ✅ (граница доверия stdio задокументирована — auth вне объёма текущего транспорта).
- [x] **Волна 10 — фичи remote/SSH (2026-09-18):** E1 ✅, E2 ✅ (см. волну 5).
- [x] **Волна 11 — чистка и решения (2026-09-18):** C11 ✅ (мёртвый `sandbox.py` удалён), C12 ✅ (компакторы — осознанный резерв), E5 ⏸ WON'T DO NOW, C7 → no-op, HARNESS_ANALYSIS/ARCHITECTURE/DEVELOPMENT/README актуализированы.
- [x] **Волна 12 — покрытие (2026-09-18):** C13 ✅ (`agent_loop` 47% → 96%, `main.py` 80% → 100%, `loki`/`prometheus` 19% → 92%/89%), покрытие unit **68.67% → 75%**, CI-гейт **65 → 72**; Python 3.12 прогоняется локально.
- [x] **Волна 13 — фичи и проверяемость (2026-09-18):** E3 ✅ (jump host), E4a ✅ (k8s multi-cluster — docs), E4b ✅ (PG multi-target), C14 ✅ (opt-in E2E-тест реального SSH).
- [x] **Волна 14 — покрытие tools + композитная диагностика (2026-09-25):** C15 ✅ (docker 28% → 100%, k8s 29% → 92%, netdiag 45% → 92%, redis 45% → 91%; unit **76% → 85%**, 346 → 418 passed), E6 ✅ (`diagnose_host` / `diagnose_web_service` — параллельные композитные срезы, +7 тестов). Заодно убран мёртвый `get_config` из README EN/RU (такого инструмента не существовало).
- [x] **Волна 15 — покрытие tools (2026-09-25):** C16 ✅ (`postgres/tools.py` 42% → 100%, Linux 56% → 96%, Nginx 68% → 97%); полный гейт **472 passed, 5 skipped**, unit coverage **90.35%**.
- [x] **Волна 16 — CI fixes (2026-09-25):** B11 ✅ — обновлён bind9 в образе (Trivy: 0 HIGH/CRITICAL, 0 secrets), исправлен docs-guard для локального `diagnosis_state.md`.

Открыты вне волн: Python 3.13 и полный integration в CI (ожидают пуша), F#13 (auth — решение принято: вне объёма stdio, см. D7), «Сабагенты» и подключение компакторов (осознанно не делаем — см. HARNESS_ANALYSIS).

После каждой волны прогонять гейты: `ruff check`, `ruff format --check`, `mypy`, `bandit`, `pytest`, валидация YAML, баланс code-fence в `*.md`.

