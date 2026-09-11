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
