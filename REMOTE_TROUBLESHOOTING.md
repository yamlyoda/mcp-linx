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

### 2. SSH Tunnel Support (HIGH) — ✅ FIXED (2026-09-18)
**Problem**: PostgreSQL config mentions SSH tunnel but no implementation exists.

**Implemented**: `SSHTunnel` (`src/mcp_linx/adapters/ssh_pool.py`) — local port forwarding via
`transport.open_channel("direct-tcpip", ...)`. `PostgresPlugin` starts it when
`plugins.postgres.ssh.tunnel: true` and connects to the tunnel's local address:

```yaml
plugins:
  postgres:
    host: db.internal        # resolved on the SSH side
    port: 5432
    ssh:
      host: bastion          # SSH server to tunnel through
      username: ops
      key_file: ~/.ssh/id_rsa
      tunnel: true           # opt-in; requires ssh.host
```

Redis needs no tunnel: its tools execute `redis-cli` on the remote host over SSH.

**Verification**: `tests/unit/test_ssh_tunnel.py` (forwarding with a fake transport) and
`tests/unit/test_postgres_tunnel.py` (plugin wiring). End-to-end verification against a
real SSH server is still pending — it is not covered in CI.

`import SSHTunnel` → `mcp_linx.adapters.ssh_pool.SSHTunnel`.

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

### 6. Connection Health Monitoring (MEDIUM) — 🟡 PARTIAL
**Problem**: Stale connections not detected. Tool calls fail with cryptic errors.

**Needed**:
- Keep-alive mechanism — ✅ DONE (`ssh_pool.py`: `transport.set_keepalive(30)` + `is_active()` check with reconnect of dead clients)
- Automatic reconnection — ✅ DONE (dead client → reconnect; live-but-broken transport → retry + drop + reconnect, E1)
- Connection health checks — ❌ TODO (no metrics/probes; keepalive + is_active() only)

**Status**: keepalive, dead-client reconnect and retry for connection-level errors are implemented; metrics/probes remain open.

---

### 7. Async SSH Library (PERFORMANCE) — ⏸ WON'T DO NOW (2026-09-18)

**Problem**: `paramiko` is synchronous, using `run_in_executor` which blocks threads.

**Decision**: not planned. E1 (retry/reconnect) and E2 (tunnel) are implemented on top of
paramiko, and diagnostic commands are short and read-only, so the executor is not a
bottleneck. An `asyncssh` migration would rewrite the whole SSH layer (pool, tunnel,
retry) and require a fresh real-SSH verification cycle.

**Revisit if**: SSH concurrency grows to dozens of parallel sessions, or native async
cancellation becomes a requirement.

---

### 8. Timeout and Retry Logic (MEDIUM) — 🟡 PARTIAL (retry done, no library)
**Problem**: Network issues cause immediate failures. No retry mechanism.

**Implemented (2026-09-18)**: `exec_command_with_retry` in `ssh_pool.py` retries
**connection-level** errors (`SSHException`, `EOFError`, `OSError`, `ConnectionError`),
drops the dead client from the pool and reconnects. Configured per host/plugin:
`retry_attempts` (default 2; `1` disables) and `retry_backoff_seconds` (default 0.5,
linear growth). A non-zero command exit code is a normal result and is not retried.

**Not done**: no `tenacity` dependency (not needed for the current linear backoff), and
no jitter/circuit breaker.

**Verification**: `tests/unit/test_ssh_retry.py`.

---

## Implementation Priority

| Priority | Feature | Effort | Status |
|----------|---------|--------|--------|
| P0 | Multi-host support | Medium | ✅ FIXED |
| P0 | Connection pooling | Medium | ✅ FIXED |
| P1 | SSH tunnel for PostgreSQL | Low | ✅ FIXED (2026-09-18; E2) |
| P1 | Host key verification | Low | ✅ FIXED |
| P1 | Connection health monitoring | Low | 🟡 PARTIAL (keepalive + dead-client reconnect + retry done; metrics/probes open) |
| P2 | Jump host support | Medium | TODO |
| P2 | Async SSH library | High | ⏸ WON'T DO NOW (paramiko + retry/tunnel sufficient; revisit on high concurrency) |
| P2 | Retry logic | Low | ✅ FIXED (2026-09-18; E1) |
| P3 | Connection manager pattern | High | TODO |

---

## Quick Wins

1. ✅ **Add `host` parameter to tool calls** — done for `linux_*`, `nginx_*` (except `nginx_stub_status`), `systemd_*`
2. **Add keep-alive to SSH** — ✅ DONE (`transport.set_keepalive(30)` in `ssh_pool.py`)
3. **Add connection retry** — ✅ DONE (`exec_command_with_retry` in `ssh_pool.py`; `retry_attempts` / `retry_backoff_seconds`, connection errors only)
4. **Document SSH tunnel setup** — ✅ DONE (README → SSH reliability: retries and tunnels; `SSHTunnel` + `plugins.postgres.ssh.tunnel: true`)

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
