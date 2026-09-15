# Remote Troubleshooting Analysis — MCP-Linx

## Current State

Remote troubleshooting is supported: multi-host registry, SSH connection pooling, and host-key verification are implemented. Remaining gaps (SSH tunnel, bastion, async SSH) are listed below.

---

## What Works Now

### ✅ Multi-Host Registry (SSH)
- `hosts:` section in `config/settings.yaml` defines named targets
- `host` parameter on `linux_*`, `nginx_*` (except `nginx_stub_status`) and `systemd_*` tools
- Shared SSH connection pool with reuse (`SSHConnectionPool`)

### ✅ SSH Connectivity (Linux, Nginx)
- SSH adapter with key-based and password auth
- Remote command execution
- Configurable per-plugin SSH settings

### ✅ Docker Remote API
- TCP connection to remote Docker daemon
- TLS support (configured but not fully tested)

### ✅ PostgreSQL Remote TCP
- Direct TCP connection to remote PostgreSQL
- SSL mode support

---

## What's Missing for Production Remote Troubleshooting

### 1. Multi-Host Support (CRITICAL) — ✅ FIXED
**Problem**: Each plugin connects to only one host. Real troubleshooting requires accessing multiple servers.

**Fixed**: A host registry (`src/mcp_linx/multihost.py`, class `HostRegistry`) reads the `hosts:` section of `config/settings.yaml`. Tools of the `linux`, `nginx` (except `nginx_stub_status`) and `systemd` plugins accept a `host` parameter — the name of a host from the registry — and run commands over SSH through a shared connection pool (`_run_command(..., host=host)` → `_resolve_adapter(host)`).

```yaml
hosts:
  web-1:
    host: 10.130.0.23
    port: 22
    username: user
    key_file: ~/.ssh/id_rsa
    password: null
    host_key_policy: reject   # reject | warning | auto_add
    known_hosts: null
```

See [Usage Example](#usage-example) for a JSON-RPC snippet. In short: `linux_host_stats`
with `{"host": "web-1"}` runs on `web-1`; if `host` is omitted, the local machine is used.

---

### 2. SSH Tunnel Support (HIGH)
**Problem**: PostgreSQL config mentions SSH tunnel but no implementation exists.

**Current config**:
```yaml
postgres:
  ssh:
    tunnel_host: null  # Not implemented!
```

**Needed**: Automatic SSH tunnel creation for PostgreSQL, Redis, etc.

**Solution**: Implement `SSHTunnelAdapter` using `sshtunnel` library.

---

### 3. Connection Pooling (HIGH) — ✅ FIXED
**Problem**: Each tool call may create new SSH connections. No connection reuse.

**Fixed**: `src/mcp_linx/adapters/ssh_pool.py` provides `SSHConnectionPool` (persistent, reusable paramiko clients keyed by host) and `RemoteHostAdapter` (same command interface as local adapters, but executes over SSH). Connections are reused across tool calls and closed on server shutdown via `HostRegistry.close_all()`.

---

### 4. SSH Host Key Verification (SECURITY) — ✅ FIXED
**Problem**: `AutoAddPolicy()` accepts any host key — vulnerable to MITM attacks.

**Fixed**: Policy is now config-driven with **RejectPolicy by default**:
```python
policy = str(self.config.get("host_key_policy", "reject")).lower()
if policy == "auto_add":
    self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
elif policy == "warning":
    self._client.set_missing_host_key_policy(paramiko.WarningPolicy())
else:
    self._client.set_missing_host_key_policy(paramiko.RejectPolicy())
```

Config options per SSH adapter (`config/settings.yaml`):
- `host_key_policy`: `reject` (default) | `warning` | `auto_add`
- `known_hosts`: path to known_hosts file (default: system `~/.ssh/known_hosts`)

---

### 5. Jump Host / Bastion Support (MEDIUM)
**Problem**: Enterprise environments often require connecting through a bastion host.

**Solution**: Implement proxy command support using paramiko channel.

---

### 6. Connection Health Monitoring (MEDIUM)
**Problem**: Stale connections not detected. Tool calls fail with cryptic errors.

**Needed**:
- Keep-alive mechanism
- Automatic reconnection
- Connection health checks

---

### 7. Async SSH Library (PERFORMANCE)
**Problem**: `paramiko` is synchronous, using `run_in_executor` which blocks threads.

**Solution**: Consider `asyncssh` for native async support.

---

### 8. Timeout and Retry Logic (MEDIUM)
**Problem**: Network issues cause immediate failures. No retry mechanism.

**Solution**: Use `tenacity` library for retry with exponential backoff.

---

## Implementation Priority

| Priority | Feature | Effort | Status |
|----------|---------|--------|--------|
| P0 | Multi-host support | Medium | ✅ FIXED |
| P0 | Connection pooling | Medium | ✅ FIXED |
| P1 | SSH tunnel for PostgreSQL | Low | TODO |
| P1 | Host key verification | Low | ✅ FIXED |
| P1 | Connection health monitoring | Low | TODO |
| P2 | Jump host support | Medium | TODO |
| P2 | Async SSH library | High | TODO |
| P2 | Retry logic | Low | TODO |
| P3 | Connection manager pattern | High | TODO |

---

## Quick Wins

1. ✅ **Add `host` parameter to tool calls** — done for `linux_*`, `nginx_*` (except `nginx_stub_status`), `systemd_*`
2. **Add keep-alive to SSH** — prevents connection timeout
3. **Add connection retry** — handles transient network issues
4. **Document SSH tunnel setup** — manual tunnel creation guide

---

## Usage Example

```jsonc
// JSON-RPC tool call — run on the host named "web-1" from the `hosts:` registry
{ "name": "linux_host_stats", "arguments": { "host": "web-1" } }

// Omit `host` to run on the local machine (primary adapter)
{ "name": "linux_host_stats", "arguments": {} }
```

If `host` is omitted, the local machine is used. An unknown name raises a `KeyError`
listing the available hosts; using `host` without a `hosts:` section raises a
`RuntimeError` ("Multi-host not configured").

> Note: `netdiag_*` tools also take a `host` argument, but there it is the **probe
> target** (IP/hostname), not a registry name. `redis_*` and the API-based plugins
> (`docker_*`, `postgres_*`, `kubernetes_*`, `prometheus_*`, `loki_*`) do not accept a
> registry `host` name.
