# Security Audit Report — MCP-Linx

## Summary

This document describes security findings in the MCP-Linx codebase. Issues are categorized by severity.

---

## Critical Issues

### 1. Command Injection in `linux_processes` (HIGH)
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

---

### 2. Path Traversal in `nginx_logs` (HIGH)
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

---

### 3. SQL Injection in `pg_tables` (HIGH)
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

---

## Medium Issues

### 4. Command Injection via `log_type` in `linux_logs` (MEDIUM)
**Location**: `src/mcp_linx/plugins/linux/tools.py:30`

**Problem**: User input `log_type` is used to construct file path:
```python
command = f"tail -n {lines} /var/log/{log_type}"
```

**Attack**: An attacker can inject commands:
```json
{"log_type": "syslog; cat /etc/shadow"}
```

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
6. ✅ **No hardcoded secrets** — passwords and keys are read from config
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

- [x] No hardcoded secrets (passwords, API keys, tokens) — ✅ Passwords from config/env
- [x] No personal data (PII) in source code — ✅ No PII found
- [ ] All user inputs validated — ❌ Command/SQL injection possible
- [ ] SQL queries use parameterized statements — ❌ String interpolation used
- [ ] File paths validated against traversal — ❌ Path traversal possible
- [ ] Shell commands use proper escaping — ❌ User input interpolated
- [x] Output size limited — ✅ SecurityGuard.limit_output()
- [x] Error messages don't leak sensitive info — ✅ Generic error messages
- [ ] Authentication/authorization implemented — ❌ Not implemented
- [ ] Audit logging enabled — ❌ Configured but not implemented

---

## Files Checked

| File | Status | Notes |
|------|--------|-------|
| `src/mcp_linx/main.py` | ✅ Clean | No hardcoded secrets |
| `src/mcp_linx/security.py` | ✅ Clean | Good security foundation |
| `src/mcp_linx/plugin_manager.py` | ✅ Clean | No issues |
| `src/mcp_linx/types.py` | ✅ Clean | No issues |
| `src/mcp_linx/adapters/base.py` | ✅ Clean | Safe subprocess usage |
| `src/mcp_linx/adapters/ssh.py` | ✅ Clean | No hardcoded credentials |
| `src/mcp_linx/adapters/docker.py` | ✅ Clean | No issues |
| `src/mcp_linx/plugins/linux/__init__.py` | ✅ Clean | No issues |
| `src/mcp_linx/plugins/linux/tools.py` | ❌ Vulnerable | Command injection |
| `src/mcp_linx/plugins/nginx/__init__.py` | ✅ Clean | No issues |
| `src/mcp_linx/plugins/nginx/tools.py` | ❌ Vulnerable | Path traversal |
| `src/mcp_linx/plugins/docker/__init__.py` | ✅ Clean | No issues |
| `src/mcp_linx/plugins/docker/tools.py` | ✅ Clean | No issues |
| `src/mcp_linx/plugins/postgres/__init__.py` | ✅ Clean | No hardcoded credentials |
| `src/mcp_linx/plugins/postgres/tools.py` | ❌ Vulnerable | SQL injection |
| `config/settings.yaml` | ✅ Clean | Passwords from env |
| `tests/conftest.py` | ✅ Clean | Test fixtures only |
