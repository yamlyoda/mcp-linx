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

## v1.1 — New Plugins (DONE 2026-09-09)

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
