# Security Audit Report — MCP-Linx

## Summary

This document describes security findings in the MCP-Linx codebase. Issues are categorized by severity.

---

## Critical Issues

> **Status (2026-09-18): all three findings below are FIXED and verified in code.**
> They are kept as history; each entry has a `Fixed` note with the current
> verification. Line numbers are from the original audit date and no longer point
> at the reviewed code — see `Files Checked` for current locations.

### 1. Command Injection in `linux_processes` (HIGH) — ✅ FIXED
**Location**: `src/mcp_linx/plugins/linux/tools.py:188`

**Problem**: User input `filter_str` is directly interpolated into a shell command:
```python
command = f"ps aux | grep -i '{filter_str}' | head -{limit}"
```

**Attack**: An attacker can inject arbitrary shell commands:
```json
{"filter_str": "'; rm -rf / #"}
```
Result: `ps aux | grep -i ''; rm -rf / #' | head -50`

**Fix**: Use `shlex.quote()` or pass arguments as a list:
```python
import shlex

command = f"ps aux | grep -i {shlex.quote(filter_str)} | head -{limit}"
```

**Fixed (2026-09)**: implemented exactly as above — `plugins/linux/tools.py`,
`linux_processes` (`safe_filter = shlex.quote(filter_str)`).

---

### 2. Path Traversal in `nginx_logs` (HIGH) — ✅ FIXED
**Location**: `src/mcp_linx/plugins/nginx/tools.py:157`

**Problem**: User input `log_type` is used to construct file path without validation:
```python
else:
    log_file = f"{config_path}/{log_type}"
```

**Attack**: An attacker can read arbitrary files:
```json
{"log_type": "../../etc/passwd"}
```

**Fix**: Validate `log_type` against an allowlist:
```python
ALLOWED_LOG_TYPES = ["error", "access", "error_full", "access_full"]
if log_type not in ALLOWED_LOG_TYPES:
    return ToolResult.error(f"Invalid log_type. Allowed: {ALLOWED_LOG_TYPES}")
```

**Fixed (2026-09)**: `log_type` is matched against an explicit allowlist
(`error`/`access`/`error_full`/`access_full`) in `plugins/nginx/tools.py`; no
user-controlled path segments remain.

---

### 3. SQL Injection in `pg_tables` (HIGH) — ✅ FIXED
**Location**: `src/mcp_linx/plugins/postgres/tools.py:223`

**Problem**: User input `schema` is directly interpolated into SQL query:
```python
query = f"""
    ...
    WHERE schemaname = '{schema}'
    ...
"""
```

**Attack**: An attacker can execute arbitrary SQL:
```json
{"schema": "public'; DROP TABLE users; --"}
```

**Fix**: Use parameterized queries:
```python
query = """
    ...
    WHERE schemaname = %s
    ...
"""
tables = await plugin._execute_query(query, (schema,))
```

**Fixed (2026-09)**: `pg_tables` validates `schema` against an allowlist
(`public`, `pg_catalog`, `information_schema`) **and** uses a parameterized query
(`WHERE schemaname = %s`, params `(schema,)`).

---

## Medium Issues

### 4. Command Injection via `log_type` in `linux_logs` (MEDIUM) — ✅ FIXED
**Location**: `src/mcp_linx/plugins/linux/tools.py` (was line 30)

**Problem**: User input `log_type` was used to construct file path:
```python
command = f"tail -n {lines} /var/log/{log_type}"
```

**Attack**: An attacker can inject commands:
```json
{"log_type": "syslog; cat /etc/shadow"}
```

**Fix applied**: `log_type` validated against `_ALLOWED_LOG_FILES` allowlist
(`dpkg.log, syslog, messages, kern.log, auth.log, user.log, boot.log, cron.log,
faillog, wtmp, btmp, dmesg, lastlog`) + predefined aliases (`journal`, `auth`,
`kern`, `syslog`, `messages`). Unknown values return `ToolResult.error`:

**Fix**: Validate `log_type` against an allowlist:
```python
ALLOWED_LOG_TYPES = ["syslog", "messages", "auth", "kern", "docker", "nginx"]
if log_type not in ALLOWED_LOG_TYPES:
    return ToolResult.error(f"Invalid log_type")
```

---

### 5. SecurityGuard Bypass (MEDIUM)
**Location**: `src/mcp_linx/security.py:55-86`

**Problem**: `validate_command()` only checks the base command, not arguments. Commands like `ps`, `grep`, `cat` are in the read-only list, but they can be used to:
- Read sensitive files: `cat /etc/shadow`
- Exfiltrate data: `grep -r 'password' /`

**Fix**: Implement path validation for file-reading commands:
```python
def validate_command(self, command: str) -> None:
    # ... existing checks ...
    
    # Additional check for file paths in commands
    file_reading_cmds = ["cat", "grep", "head", "tail", "less", "more"]
    if any(command.startswith(cmd) for cmd in file_reading_cmds):
        # Extract file paths and validate them
        paths = self._extract_paths(command)
        for path in paths:
            if self._is_sensitive_path(path):
                raise SecurityError(f"Access to {path} is restricted")
```

---

### 6. No Input Validation on `lines` Parameter (LOW)
**Location**: Multiple tools

**Problem**: The `lines` parameter is converted to int but not validated for reasonable bounds in some tools.

**Fix**: Add Pydantic validation or explicit bounds checking:
```python
lines = max(1, min(int(params.get("lines", 100)), 1000))
```

---

## Positive Security Features

1. ✅ **SecurityGuard with readonly mode** — blocks write operations
2. ✅ **Dangerous pattern detection** — regex-based blocking of known dangerous commands
3. ✅ **Output size limiting** — prevents memory exhaustion
4. ✅ **Log line limiting** — prevents log flooding
5. ✅ **Pydantic input validation** — type safety for tool inputs
6. ✅ **No hardcoded secrets** — passwords and keys are read from YAML configuration.
   `${VAR}` / `${VAR:-default}` expand the process environment before YAML parsing.
   Plugin secrets must not be added to the server `.env` (unknown fields are rejected).
   Missing variables without defaults log a warning and retain the entire raw YAML;
   this is not fail-fast secret validation. See `docs/DEVELOPMENT.md`.
7. ✅ **No personal data** — no PII in source code

---

## Recommendations

### Immediate Actions
1. Fix command injection in `linux_processes`
2. Fix path traversal in `nginx_logs`
3. Fix SQL injection in `pg_tables`
4. Fix command injection in `linux_logs`

### Short-term Improvements
5. Strengthen SecurityGuard to validate file paths
6. Add input validation for all user-provided parameters
7. Implement parameterized queries for all SQL operations
8. Add security tests

### Long-term Improvements
9. Implement audit logging for all tool executions
10. Add rate limiting for tool calls
11. Implement RBAC (Role-Based Access Control)
12. Add secrets management integration (e.g., HashiCorp Vault)

---

## Security Checklist

- [x] No hardcoded secrets (passwords, API keys, tokens) — ✅ No literals in code; YAML supports process-environment substitution `${VAR}` / `${VAR:-default}` (see configuration limitations above)
- [x] No personal data (PII) in source code — ✅ No PII found
- [x] All user inputs validated — ✅ Command inputs use shlex.quote(), path allowlists
- [x] SQL queries use parameterized statements — ✅ pg_tables uses %s parameterized query
- [x] File paths validated against traversal — ✅ nginx_logs uses allowlist
- [x] Shell commands use proper escaping — ✅ shlex.quote() applied
- [x] Output size limited — ✅ SecurityGuard.limit_output()
- [x] Error messages don't leak sensitive info — ✅ Generic error messages
- [ ] Authentication/authorization implemented — ❌ Not implemented, and **by design out of scope for the current transport**. The server speaks MCP over stdio (`python -m mcp_linx.main`), so its trust boundary is the parent process that spawns it: there is no network listener to authenticate against. Consequences that must be respected in deployment: run it only in a trusted local context (same user as the MCP client), do not expose it through a network bridge that forwards stdin/stdout of an untrusted party, and treat every tool as fully authorized for the configured hosts. **Before adding any HTTP/SSE transport or a shared multi-tenant deployment, authentication and authorization must be implemented first** (see Long-term Improvements #11).
- [x] Audit logging enabled — ✅ Implemented in Phase 1 (audit.py + agent_loop integration). Scope: plugin tool handlers; system tools are not rate limited, and rate-limit rejections are not recorded.
- [x] Rate limiting for tool calls — ✅ `security.rate_limit_max_calls` / `rate_limit_window_seconds` applied in `agent_loop._make_handler`; rejections are audited (2026-09-18)
- [x] Privileged tools gated by config — ✅ `plugins.netdiag.privileged_tools: false` by default (`tcp_connect_as`, `tcpdump_probe` return error with manual command)
- [x] New diagnostic commands restricted to read-only subcommands — ✅ `bpftool {show,dump}`, `nft list`, `ip {rule,route} show`, `iptables -S`, `ufw status` only

---

## CI Vulnerability Scanning (added 2026-09)

CI job `security` (`.github/workflows/ci.yml`) запускается параллельно с lint/test на каждый push/PR:

| Инструмент | Что проверяет | Команда |
|------------|---------------|---------|
| **Bandit** (SAST) | Уязвимости в коде: инъекции, hardcoded секреты, небезопасные вызовы | `bandit -c pyproject.toml -r src/mcp_linx` |
| **pip-audit** (SCA) | Известные CVE во всех зависимостях (PyPI Advisory DB / OSV) | `pip-audit --skip-editable` |
| **Gitleaks** | Секреты/токены/пароли в коде и git-истории | `gitleaks/gitleaks-action@v2` |
| **Trivy** (job `docker-build`) | CVE + секреты в Docker-образе (HIGH/CRITICAL → fail) | `aquasecurity/trivy-action@v0.36.0` (последний; релиз immutable) |

Все хуки продублированы локально в `.pre-commit-config.yaml` (ruff, bandit, gitleaks, mypy).

Локальный прогон:
```bash
bandit -c pyproject.toml -r src/mcp_linx   # 0 findings
pip-audit --skip-editable                  # No known vulnerabilities found
```

Подавления (`# nosec <ID>`) допустимы только с обоснованием в комментарии **перед** маркером:
`# <причина>  # nosec B601`. Сейчас обоснованы: B101 (инварианты после connect), B110
(intentional cleanup), B507 (opt-in ветки конфига SSH, дефолт reject), B601 (команды проходят
`SecurityGuard.validate_command` / статические).

Дополнительно по результатам аудита bandit исправлены **2 реальных места SQL-интерполяции**
в `postgres/tools.py` (`pg_locks` pid, `pg_slow_queries` threshold/limit) — переведены на
параметризованные запросы `%s`.

## Files Checked

| File | Status | Notes |
|------|--------|-------|
| `src/mcp_linx/main.py` | ✅ Clean | No hardcoded secrets |
| `src/mcp_linx/security.py` | ✅ Clean | Good security foundation |
| `src/mcp_linx/plugin_manager.py` | ✅ Clean | No issues |
| `src/mcp_linx/types.py` | ✅ Clean | No issues |
| `src/mcp_linx/adapters/base.py` | ✅ Clean | Safe subprocess usage |
| `src/mcp_linx/adapters/ssh.py` | ✅ Clean | Host key policy RejectPolicy by default (config: reject|warning|auto_add), known_hosts supported |
| `src/mcp_linx/adapters/docker.py` | ✅ Clean | No issues |
| `src/mcp_linx/plugins/linux/__init__.py` | ✅ Clean | No issues |
| `src/mcp_linx/plugins/linux/tools.py` | ✅ Fixed | Command injection fixed with shlex.quote() |
| `src/mcp_linx/plugins/nginx/__init__.py` | ✅ Clean | No issues |
| `src/mcp_linx/plugins/nginx/tools.py` | ✅ Fixed | Path traversal fixed with allowlist |
| `src/mcp_linx/plugins/docker/__init__.py` | ✅ Clean | No issues |
| `src/mcp_linx/plugins/docker/tools.py` | ✅ Clean | No issues |
| `src/mcp_linx/plugins/postgres/__init__.py` | ✅ Clean | No hardcoded credentials |
| `src/mcp_linx/plugins/postgres/tools.py` | ✅ Fixed | SQL injection fixed with parameterized query |
| `config/settings.yaml` | ✅ Clean | Secrets from process environment via `${VAR}`; missing-variable fallback and YAML quoting limitations apply |
| `src/mcp_linx/adapters/ssh_pool.py` | ✅ Clean | Shared SSH path: pool, `exec_command_with_retry` (E1), `SSHTunnel` (`direct-tcpip`, E2), host-key policy unchanged |
| `src/mcp_linx/security.py` | ✅ Clean | `readonly` exposed as a property; command allowlist + dangerous patterns unchanged |
| `src/mcp_linx/plugins/docker/__init__.py` | ✅ Clean | `prune_containers` refuses to run while `security.readonly` is true (write-path gate) |
| `src/mcp_linx/harness/agent_loop.py` | ✅ Clean | Rate-limit check inside try/finally so rejections are audited with the error text |
| `tests/conftest.py` | ✅ Clean | Test fixtures only |
| `src/mcp_linx/plugins/systemd/tools.py` | ✅ Clean | `service_ip_filter`: unit + bpftool (LPM-trie→CIDR), `_UNIT_RE` allowlist |
| `src/mcp_linx/plugins/linux/tools.py` | ✅ Clean | `linux_firewall`: nft/ip rule/iptables/ufw read-only snapshot, marks parsing |
| `src/mcp_linx/plugins/netdiag/tools.py` | ✅ Clean | `tcp_connect_as`/`tcpdump_probe`: `_ALLOWED_PROBE_USERS`, `_HOST_RE`, count≤50, timeout≤15 |
| `src/mcp_linx/plugins/netdiag/__init__.py` | ✅ Clean | `_run_privileged`: строгий префикс-allowlist (`runuser -u `, `timeout `) + DANGEROUS_PATTERNS |
