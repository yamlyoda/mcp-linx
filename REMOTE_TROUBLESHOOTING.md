# Remote Troubleshooting Analysis — MCP-Linx

## Current State

The project has basic remote connectivity but needs enhancements for production remote troubleshooting.

---

## What Works Now

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

### 1. Multi-Host Support (CRITICAL)
**Problem**: Each plugin connects to only one host. Real troubleshooting requires accessing multiple servers.

**Current**:
```yaml
plugins:
  linux:
    ssh:
      host: "server1.example.com"  # Only one host!
```

**Needed**: Support for multiple hosts per plugin or host parameter in tool calls.

**Solution Options**:
- A) Pass host as tool parameter
- B) Create plugin instances per host
- C) Use a host registry with connection pooling

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

### 3. Connection Pooling (HIGH)
**Problem**: Each tool call may create new SSH connections. No connection reuse.

**Current flow**:
```
Tool call → Plugin.initialize() → SSH connect → Execute → Disconnect
```

**Needed**: Connection pooling for persistent connections.

---

### 4. SSH Host Key Verification (SECURITY)
**Problem**: `AutoAddPolicy()` accepts any host key — vulnerable to MITM attacks.

**Current**:
```python
self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
```

**Solution**: Use `RejectPolicy` by default, with optional known_hosts file.

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

| Priority | Feature | Effort |
|----------|---------|--------|
| P0 | Multi-host support | Medium |
| P0 | Connection pooling | Medium |
| P1 | SSH tunnel for PostgreSQL | Low |
| P1 | Host key verification | Low |
| P1 | Connection health monitoring | Low |
| P2 | Jump host support | Medium |
| P2 | Async SSH library | High |
| P2 | Retry logic | Low |
| P3 | Connection manager pattern | High |

---

## Quick Wins (Can Implement Now)

1. **Add host parameter to tool calls** — allows specifying target host per request
2. **Add keep-alive to SSH** — prevents connection timeout
3. **Add connection retry** — handles transient network issues
4. **Document SSH tunnel setup** — manual tunnel creation guide
