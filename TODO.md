# TODO — Architecture Review & Findings

## Critical Issues Found

### 1. ✅ Module/Package Conflict (FIXED)
**Problem**: Both `plugins/linux.py` (module) and `plugins/linux/` (package with `__init__.py`) existed simultaneously. Python imports the package first, which was empty, causing `ImportError: cannot import name 'LinuxPlugin'`.

**Fix Applied**:
- Moved plugin classes (`LinuxPlugin`, `NginxPlugin`, `DockerPlugin`, `PostgresPlugin`) into `__init__.py` of respective packages
- Deleted old `linux.py`, `nginx.py`, `docker.py`, `postgres.py` modules
- All imports now work correctly

### 2. ✅ Tools.py Files Concatenated (FIXED)
**Problem**: The `tools.py` files were concatenated from multiple parts with duplicate imports and module docstrings:
- `linux/tools.py`: Had `from __future__ import annotations` at line 143 (SyntaxError)
- `nginx/tools.py`: Had duplicate import at line 102
- `postgres/tools.py`: Had multiple duplicate sections

**Fix Applied**:
- Removed duplicate `from __future__` imports from linux/tools.py and nginx/tools.py
- Rewrote postgres/tools.py completely to remove all duplicates
- Verified all tool functions are unique and imports are correct

**Status**: Fixed

---

## Architecture Review (Part 1: Core Structure)

### Current Structure
```
src/mcp_linx/
├── __init__.py
├── main.py              # MCP server entry point (FastMCP)
├── plugin_manager.py    # Plugin registration & lifecycle
├── security.py          # SecurityGuard (readonly, validation, limits)
├── context_aggregator.py # Cross-component correlation
├── types.py             # Status, ToolResult, ComponentState, Correlation
├── adapters/
│   ├── base.py          # BaseAdapter (abstract)
│   ├── ssh.py           # SSHAdapter (paramiko)
│   └── docker.py        # DockerAdapter (docker SDK)
└── plugins/
    ├── __init__.py
    ├── base.py          # DiagnosticPlugin (abstract), PluginRegistry
    ├── linux/
    │   ├── __init__.py  # LinuxPlugin class
    │   └── tools.py     # 7 tool functions
    ├── nginx/
    │   ├── __init__.py  # NginxPlugin class
    │   └── tools.py     # 4 tool functions
    ├── docker/
    │   ├── __init__.py  # DockerPlugin class
    │   └── tools.py     # 7 tool functions
    └── postgres/
        ├── __init__.py  # PostgresPlugin class
        └── tools.py     # 7 tool functions
```

### Strengths
- Clean plugin architecture with abstract base class
- Good separation of concerns (adapters, plugins, security, context)
- SecurityGuard with readonly mode, command validation, output limits
- ContextAggregator for cross-component correlation
- Pydantic schemas for input validation

### Findings

#### 1. ✅ SSHAdapter - key_file/password FIXED
**Location**: `src/mcp_linx/adapters/ssh.py`

The SSH adapter now properly reads `key_file` and `password` from config dict and passes them to `paramiko.SSHClient.connect()`.

**Status**: Fixed (code already had the fix)

#### 2. PostgreSQL SSL mode in config but not documented
**Location**: `config/settings.yaml`, `src/mcp_linx/plugins/postgres/__init__.py`

The `ssl_mode` parameter is accepted but not documented in README or settings.yaml.

**Status**: Documentation update needed

#### 3. Nginx stub_status check missing
**Location**: `src/mcp_linx/plugins/nginx/tools.py`

README mentions `stub_status_url` but the tool doesn't implement HTTP health check.

**Status**: Feature gap

#### 4. Docker prune tool exists but adapter method is read-only info
**Location**: `src/mcp_linx/adapters/docker.py`, `src/mcp_linx/plugins/docker/tools.py`

The `prune_containers()` method in adapter only lists containers to remove but doesn't actually delete them. The tool should either be clearly labeled as "dry-run" or implement actual pruning.

**Status**: Clarification needed

#### 5. ContextAggregator correlation rules could be extended
**Location**: `src/mcp_linx/context_aggregator.py`

Current correlations:
- Docker + Nginx (cascade)
- PostgreSQL + Docker (root cause)
- Linux + components (OOM, cascade)

Missing correlations:
- Nginx + PostgreSQL (upstream backend failures)
- Linux disk space + Docker (image/container disk usage)
- Linux memory + PostgreSQL (shared memory, OOM)

**Status**: Enhancement opportunity

#### 6. Missing system tools in main.py
**Location**: `src/mcp_linx/main.py`

The `get_diagnostic_context` and `get_summary` tools are defined but not consistently registered. The `get_diagnostic_context` calls `context_aggregator.build_context()` which is async but called without `await`.

**Status**: Bug - needs fix

#### 7. ✅ No graceful shutdown handling — FIXED
**Location**: `src/mcp_linx/main.py`

Signal handlers for SIGTERM/SIGINT are now implemented in `main()`. Plugin connections are properly closed on shutdown via `plugin_manager.destroy_all()`.

**Status**: Fixed

#### 8. ✅ Missing health check endpoint — FIXED
**Location**: `src/mcp_linx/main.py`

The `system_health_check` tool is now registered as a system tool in the `AgentLoop`, exposing health check results via MCP.

**Status**: Fixed

---

## Test Coverage

### Current Coverage
- `test_security.py`: 16 tests (SecurityGuard, Pydantic schemas)
- `test_context_aggregator.py`: 9 tests (component management, correlations)

### Missing Tests
- Plugin tools (linux, nginx, docker, postgres)
- Adapters (SSH, Docker)
- PluginManager
- main.py server initialization
- Integration tests

**Status**: Test coverage needs expansion

#### 9. Docker prune is a destructive operation
**Location**: `src/mcp_linx/adapters/docker.py`, `src/mcp_linx/plugins/docker/tools.py`

The `prune_containers()` method actually deletes containers. This should be:
- Protected by SecurityGuard readonly mode
- Require explicit confirmation
- Or be renamed to `list_prunable_containers` for dry-run

**Status**: Needs decision

#### 10. ✅ Missing graceful shutdown — FIXED
**Location**: `src/mcp_linx/main.py`

Signal handlers for SIGTERM/SIGINT are now implemented. Plugin connections (SSH, Docker, PostgreSQL) are closed via `plugin_manager.destroy_all()` on shutdown.

**Status**: Fixed

#### 11. ContextAggregator is synchronous
**Location**: `src/mcp_linx/context_aggregator.py`

The ContextAggregator uses synchronous dict operations. This is fine for now but may become a bottleneck with many concurrent tool calls.

**Status**: OK for now, monitor

---

## Recommended Next Steps

### High Priority
1. ✅ Fix SSHAdapter key_file/password authentication (FIXED in adapters/ssh.py)
2. ✅ Fix async call in `get_diagnostic_context` (handled via agent_loop._make_handler with try/except)
3. ✅ Add health check MCP tool (system_health_check registered in agent_loop)
4. ✅ Add graceful shutdown handling (signal handlers in main.py)

### Medium Priority
5. Expand ContextAggregator correlation rules
6. Add plugin tool tests
7. Document SSL mode for PostgreSQL
8. Clarify Docker prune behavior (dry-run vs actual)

### Security Issues (CRITICAL - See SECURITY.md)

~~1. **Command Injection** in `linux_processes` — user input interpolated into shell command~~ ✅ FIXED: `shlex.quote()` applied
~~2. **Path Traversal** in `nginx_logs` — user input used to construct file path~~ ✅ FIXED: Allowlist for log_type
~~3. **SQL Injection** in `pg_tables` — user input interpolated into SQL query~~ ✅ FIXED: Parameterized query with `%s` + schema allowlist
~~4. **Command Injection** in `linux_logs` — user input used in file path~~ ✅ FIXED: `shlex.quote()` for journal `since` and `priority` params

### Low Priority
9. Add integration tests
10. Add Nginx stub_status HTTP check
11. Expand README with more examples
12. Implement audit logging
13. Add authentication/authorization

---

## Phase 1 — Stability & Production (DONE 2026-09-10)

### Implemented
- **Audit logging** — `src/mcp_linx/audit.py`: `AuditLogger`, `sanitize_params()` (redacts password/token/secret/api_key), JSON-lines в файл/лог. Встроен в `agent_loop._make_handler` (пишется каждый вызов: tool, plugin, status, duration_ms, params без секретов).
- **Rate limiting** — `src/mcp_linx/ratelimit.py`: `RateLimiter` скользящее окно на инструмент. Настраивается через `security.rate_limit_max_calls` / `security.rate_limit_window_seconds`. Встроен в `agent_loop._make_handler` (ключ `plugin:tool`).
- **ContextAggregator авто-наполнение** — `_seed_context_from_health()` при старте + `system_health_check` обновляет агрегатор актуальными состояниями. `last_checked` теперь ISO-метка UTC (не `loop.time()`).
- **Integration tests** — `tests/integration/` + `tests/docker-compose.test.yml` (postgres:16, nginx:1.27, redis:7) + `tests/nginx-test.conf` (stub_status). Фикстура поднимает стек и ждёт готовности, скип при отсутствии Docker.
- **Bug fix**: `pg_stats` использовал несуществующую `pg_relation_size()` → `pg_total_relation_size(...::regclass)`, убрана битая колонка size для индексов.
- **Bug fix**: `docker_stack` fixture — путь к compose-файлу через `parent.parent` (был `parent` → no such file).
- pyproject: маркер `integration`.

### Tests
- `tests/unit/test_audit_ratelimit.py`: 10 unit-тестов (sanitize, audit logger, rate limiter).
- `tests/integration/test_integration.py`: 7 integration-тестов (pg_connections/pg_stats/pg_tables, nginx stub_status/root, redis ping/info). Redis-тесты скипаются если `redis-cli` недоступен.
- **Total: 68 passed, 2 skipped.**

### Usage
```bash
# unit + integration (integration поднимет compose, ждёт Docker)
.venv/bin/python -m pytest tests/ -q

# только unit (без Docker)
.venv/bin/python -m pytest tests/unit/ -q

# только integration
.venv/bin/python -m pytest tests/integration/ -q
```

---

All variants implemented: redis, systemd, netdiag, kubernetes, prometheus, loki.

### Added
- `src/mcp_linx/plugins/redis/` — 5 tools (ping, info, clients, slowlog, memory)
- `src/mcp_linx/plugins/systemd/` — 4 tools (service_status, failed_units, service_logs, boot_analysis)
- `src/mcp_linx/plugins/netdiag/` — 4 tools (http_check, tls_check, dns_resolve, tcp_connect)
- `src/mcp_linx/plugins/kubernetes/` — 6 tools (pods, events, logs, describe, top, deployments)
- `src/mcp_linx/plugins/prometheus/` — 4 tools (query, range, alerts, targets)
- `src/mcp_linx/plugins/loki/` — 3 tools (search, labels, tail)
- `Status.UNHEALTHY` added to `src/mcp_linx/types.py`
- 3 new correlation rules in `context_aggregator.py`: redis+pg cascade, linux+k8s OOM, netdiag+nginx TLS

### Config
- `config/settings.yaml`: enabled += redis, systemd, netdiag, kubernetes, prometheus, loki + sections

### Deps
- `pyproject.toml`: redis>=5.0.0, kubernetes>=30.0.0 (httpx already present, used by netdiag/prometheus/loki)

### Tests
- `tests/unit/test_new_plugins.py`: 10 tests (redis, systemd, netdiag)
- `tests/unit/test_new_plugins2.py`: 6 tests (k8s, prometheus, loki, 2 correlations)
- Total: 41 passed (was 25)

### Docs
- `README.md`: new plugin sections (EN)
- `docs/SKILLS.md`: new skills tables, workflows, correlations

### Discovery check
- `discover_plugins()` → 10 plugins, 51 tools total


---

## Phase 3 — Features (DONE 2026-09-11)

### Implemented
- **Nginx upstream HTTP health check** — `nginx_upstream` делает реальный HTTP-чек каждого upstream через `httpx` (таймаут, нормализация URL, обработка unix-socket, live/dead списки).
- **ContextAggregator: 4 новые корреляции** — OOM→restart→5xx (тройная цепочка), postgres idle-in-transaction, replication lag→nginx, linux no-space→docker_prune.
- **Path traversal fix в nginx_logs** — `_ALLOWED_LOG_DIRS` + `_ALLOWED_LOG_NAMES` allowlist, валидация `basename` для access_log/error_log.
- **Tests** — 13 unit-тестов: TestNginxLogs (3), TestNginxUpstream (3), TestNginxConfig (2), TestContextAggregatorNewCorrelations (4), nginx_stub_status (1).

### Files Changed
- `src/mcp_linx/plugins/nginx/tools.py` — import os, константы `_ALLOWED_LOG_DIRS`/`_ALLOWED_LOG_NAMES`, валидация в `nginx_logs`.
- `tests/unit/test_base_plugins.py` — +9 тестов.
- `tests/unit/test_context_aggregator.py` — +4 теста.
- `TODO.md`, `SECURITY.md` — документация.

### Tests
- **Total: ~80+ tests, 2 skipped (redis-cli).**

---

## Phase P0 — INCIDENT_504 follow-up (DONE 2026-09-11)

Реальный инцидент 504 Gateway Timeout (VM Ubuntu 24.04, цепочка nginx → Go → PostgreSQL) выявил 3 слепые зоны сервера. Полный разбор — `docs/INCIDENT_504.md`, краткий журнал — `diagnosis_state.md` (креды вычищены: `PG_VM_HOST` + `***REDACTED***`).

### Root causes на сервере (исправлены вручную, сервер read-only — не трогаем)
1. **systemd IP-фильтр через eBPF** — `bpftool map dump` показал whitelist только `127.0.0.0/8`, `systemctl show` молчал. Фикс: drop-in `allow-db.conf` с `IPAddressAllow` для DB.
2. **nftables + blackhole** — `skuid www-data tcp dport 8080 → mark 0x64`, `table 100 = blackhole default`. Фикс: `ip daddr 127.0.0.0/8 accept` до маркировки.

### Added (5 tools)
- `src/mcp_linx/plugins/systemd/tools.py::service_ip_filter` — unit-файлы + `bpftool` (LPM-trie decode в CIDR), вердикт `hidden_filter`. Зарегистрирован в `systemd/__init__.py`.
- `src/mcp_linx/plugins/linux/tools.py::linux_firewall` — `nft list ruleset` (парсинг marks) + `ip rule` + все таблицы маршрутов (blackhole-detect) + `iptables -S` + `ufw status` + опциональный `ip route get`. Зарегистрирован в `linux/__init__.py`.
- `src/mcp_linx/plugins/netdiag/tools.py::tcp_connect_as` — проба от сервисного uid (allowlist `_ALLOWED_PROBE_USERS`, `_HOST_RE`, лимиты). Требует `privileged_tools=true`.
- `src/mcp_linx/plugins/netdiag/tools.py::tcpdump_probe` — короткий срез (count≤50, timeout≤15), 0 пакетов = дроп ниже интерфейса. Требует `privileged_tools=true`.
- `src/mcp_linx/plugins/netdiag/__init__.py` — адаптер (Local/SSH) + `_run_privileged()` со строгим префикс-allowlist (`runuser -u `, `timeout `) + проверка DANGEROUS_PATTERNS. Без адаптера раньше привилегированные пробы были невозможны.
- `src/mcp_linx/plugins/nginx/tools.py::nginx_upstream` — добавлены `proxy_connect_timeout_s` / `proxy_read_timeout_s` из конфига + `connect_ms` на каждый check + флаг `matches_proxy_connect_timeout`.

### Correlations (3 новых в context_aggregator.py)
- `timeout_equals_proxy_timeout` — измеренное время ≈ proxy_connect_timeout (±15%) → SYN-дроп, смотреть linux_firewall + service_ip_filter + tcp_connect_as.
- `process_can_but_service_cannot` (netdiag per-uid) — проба OK от одного uid, FAIL от сервисного → nft skuid / IPAllow.
- `db_host_vs_listen_mismatch` — DB_HOST vs listen_addresses → сверить ss -tlnp + pg_hba.conf.

### Security
- `security.py::READONLY_COMMANDS` += `bpftool, nft, iptables, ufw` (только read-only подкоманды).
- `config/settings.yaml::plugins.netdiag.privileged_tools: false` (по умолчанию выкл; tools возвращают error с готовой ручной командой).
- Валидация: `_UNIT_RE` (юниты), `_HOST_RE` (хосты), `_ALLOWED_PROBE_USERS`, iface regex, `shlex.quote` везде.

### Tests (17 новых)
- `test_new_plugins.py`: service_ip_filter ×3 (no filter / hidden filter / bad unit), tcp_connect_as ×3 (disabled / bad user / ok), tcpdump_probe ×2 (disabled / no packets).
- `test_base_plugins.py::TestLinuxFirewall` ×2 (clean / blackhole detected).
- `test_context_aggregator.py::TestContextAggregatorIncident504` ×5 (timeout match / match without metrics / no correlation when differ / per-uid / db_host mismatch).
- **Total: 95 passed, 2 skipped.**

### Discovery check
- `discover_plugins()` → 10 plugins, 56 tools (было 51) + 3 system tools.

---

## Audit 2026-09-15 — Known Issues & Backlog

**Контекст аудита:** multi-host реализован (`src/mcp_linx/multihost.py`, `src/mcp_linx/adapters/ssh_pool.py`); `discover_plugins()` → 10 плагинов / 56 tools + 3 system tools; `pytest` → 111 passed, 2 skipped. Ниже — результаты ревизии кода, конфига, CI и документации. **Изменений в код не вносилось** — только фиксация находок; каждая проверена чтением кода и/или прогоном.

Статус репозитория на момент записи: правки multi-host + docs от 2026-09-15 **уже закоммичены** (HEAD `d75bc1f`, ветка `main`); в рабочем дереве изменён только этот `TODO.md`.

> NB: пункт «#### 10. ✅ Missing graceful shutdown — FIXED» выше **не соответствует действительности** — см. A2. Запись «56 tools (было 51)» в конце предыдущего раздела — исторический лог фазы, править не нужно.

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

- [ ] **B10. CI `docker-build` теперь запускается, но Trivy проваливает job: 76 HIGH/CRITICAL в образе `python:3.11-slim` (Debian 13.6, 147 пакетов).**
  - `severity: HIGH,CRITICAL` + `exit-code: "1"` → `--severity HIGH,CRITICAL` фильтрует, значит 76 — именно HIGH/CRITICAL. Большинство из них, вероятно, в apt-утилитах модели A (`postgresql-client`, `redis-tools`, `openssh-client`, `curl` из Debian trixie, где CVE до сих пор `no-fix`). Полный список — в логах шага Trivy в GitHub Actions (локально воспроизвести тяжело).
  - Варианты (выбор за заказчиком, т.к. это security-posture):
    1. `ignore-unfixed: true` — фейлиться только на CVE с upstream-патчем (рекомендовано для rolling/stable base image);
    2. заморозить base image (`FROM python:3.11.10-slim@sha256:...`) + регулярный `docker/build-push-action `--platform` и `docker scout`/cron;
    3. вывести `format: sarif`+upload-to-code-scanning или `format: json` в артефакт для triage;
    4. заменить apt-утилиты на образы с чужими CVE (убрать `postgresql-client`/`redis-tools`, если unused) и/или `.trivyignore` для признанных `will_not_fix`.
  - Effort: 1–3 ч на воплотение + согласование порога.
  - Статус: 🟡 **не фикшу** без одобрения — понижение/повышение порога сканера — вопрос политики репозитория.

### C. Упаковка и гигиена репозитория

- [ ] **C1. Нет файла `LICENSE`**, при этом README: «MIT» и pyproject: `license = {text = "MIT"}`; classifier `Development Status :: 3 - Alpha` конфликтует с `version = "1.0.0"`. → добавить `LICENSE` (+ `license-files`, PEP 639), согласовать статус разработки.
- [ ] **C2. Нет `CHANGELOG.md`** — завести и перенести вехи фаз из этого файла.
- [ ] **C3. Нет `py.typed`** (PEP 561) при mypy strict и типизированном публичном API.
- [ ] **C4. Нет `.env.example`**, хотя `pydantic-settings` читает `.env` (`main.py:31`, `env_file=".env"`) и `.gitignore` разрешает `!.env.example`. Задокументировать фактически поддерживаемые имена: `CONFIG_PATH`, `LOG_LEVEL`, `MCP_SERVER_NAME`, `MCP_SERVER_VERSION`, `AGENT_LOOP` (+ `PLUGINS`, если починить — A10); связано с A4.
- [ ] **C5. Метаданные-заглушки:** `authors = mcp-linx <mcp-linx@example.com>`; нет `[project.urls]` (Homepage/Repository/Issues).
- [ ] **C6. `HARNESS_ANALYSIS.md` лежит в корне** — внутренний анализ, тогда как README ведёт список документации в `docs/`. Переместить или оставить осознанно.
- [ ] **C7.** `diagnosis_state.md` — корректно в `.gitignore` («креды, kept local only»), **не трогать**.

### D. Документация (следует за фиксами кода)

- [ ] **D1.** README (EN+RU, Security): убрать или исправить пункт про `allowed_hosts` — после решения по A3.
- [ ] **D2.** Добавить раздел про env-переменные (реальные имена полей `Settings`, см. A10) и `${VAR}` (A4), audit-лог и путь к нему (A6), корректное завершение по SIGTERM / `docker stop` (A2). Сейчас в `docs/DEVELOPMENT.md` про env **нет ничего**.
- [ ] **D3.** README Configuration: пометить/убрать `tunnel_host` (A5) и секцию `logging:` (A7); задокументировать `rate_limit_*` (A9).
- [ ] **D4.** REMOTE_TROUBLESHOOTING #6 «Connection health monitoring» помечен как TODO, **хотя частично уже реализован**: в пуле есть `transport.set_keepalive(30)`, проверка `is_active()` и реконнект мёртвого клиента. Остаётся ретрай для «живого, но разорванного» транспорта + метрики. Обновить статус.
- [ ] **D5.** SECURITY.md: исправить ложную аттестацию про env-переменные (A4) — приоритетно, это security-отчёт.

### E. Роадмап фич (remote/SSH)

- [ ] **E1 (Low).** Retry с backoff и прозрачный reconnect для SSH-команд (REMOTE_TROUBLESHOOTING #8).
- [ ] **E2 (Low).** SSH tunnel для PostgreSQL/Redis (REMOTE_TROUBLESHOOTING #2) — либо вместо реализации удалить ключи конфига (A5).
- [ ] **E3 (Medium).** Jump host / bastion (paramiko proxy channel, REMOTE_TROUBLESHOOTING #5).
- [ ] **E4.** Multi-host для API-плагинов (k8s через SSH + `kubectl`, PostgreSQL через туннель) — требует отдельной оценки объёма.
- [ ] **E5 (High).** Переход на `asyncssh` вместо `run_in_executor` (REMOTE_TROUBLESHOOTING #7) — не рекомендуется в ближайшую итерацию.

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

### G. Предлагаемый порядок работ (волны)

- [ ] **Волна 1 — правда в доках:** D1, D4, D5, C1 (доки и security-отчёт обещают несуществующее).
- [ ] **Волна 2 — быстрые баги:** A1, A2, A6, A5.
- [ ] **Волна 3 — секьюрити-контур:** A4 (+ C4), A3 (развилка a/b), A7, A9, A10.
- [ ] **Волна 4 — качество:** B1–B7, C2, C3, C5.
- [ ] **Волна 5 — рефакторинг и фичи:** A8, E1, E2.

После каждой волны прогонять гейты: `ruff check`, `ruff format --check`, `mypy`, `bandit`, `pytest`, валидация YAML, баланс code-fence в `*.md`.
