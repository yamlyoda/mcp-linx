# MCP-Linx — MCP Server for Linux Infrastructure Diagnostics

> Русская версия: [`README.ru.md`](./README.ru.md).

MCP-Linx is an MCP (Model Context Protocol) server for Linux infrastructure diagnostics. It provides tools for monitoring and diagnosing components: Linux host, Nginx, Docker, PostgreSQL, Redis, Systemd, Netdiag, Kubernetes, Prometheus, Loki.

---

## Installation

```bash
# Create a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"
```

---

## Running the Server

```bash
# Start MCP server (stdio mode)
python -m mcp_linx.main

# With MCP Inspector for debugging
npx @modelcontextprotocol/inspector python -m mcp_linx.main
```

### Docker

Two deployment models with the same image:

- **Model A (default, safe)** — isolated container diagnosing *remote* hosts over SSH; postgres/redis/prometheus/loki/k8s over the network.
- **Model B (host)** — diagnosing the *local* host (Linux only): requires `pid: host`, `network_mode: host` and read-only mounts (see `docker-compose.yml`). Note: mounting `docker.sock` grants root-equivalent access to the Docker host.

```bash
# Build
docker build -t mcp-linx:latest .

# Run via compose (stdio; MCP clients: command=docker, args=["run","-i","--rm","mcp-linx:latest"])
docker compose run --rm mcp-linx

# Claude Desktop / MCP Inspector config
{
  "mcpServers": {
    "mcp-linx": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "-v", "/absolute/path/config:/app/config:ro", "mcp-linx:latest"]
    }
  }
}
```

---

## Configuration

Main configuration file: `config/settings.yaml`

Environment variables: copy `.env.example` → `.env` for the five server settings
only (names without a prefix). Plugin secrets must be supplied in the **process
environment**, not added to `.env`: unknown dotenv keys cause a validation error.
YAML expands `${VAR}` / `${VAR:-default}` from that environment; a missing variable
without a default logs a warning and falls back to the entire unexpanded YAML.
An empty environment value does not trigger the default. Expansion is textual
(before YAML parsing), so values must remain valid in their YAML quoting context.
See [Environment and configuration](docs/DEVELOPMENT.md#environment-and-configuration)
for local and Docker setup, audit logging, and shutdown behavior.

`plugins.enabled` selects initialization only. All loaded plugins still contribute
MCP tools and health checks; excluded plugins may return initialization errors.
This setting does not hide tools and is not an access-control boundary.

```yaml
security:
  readonly: true                    # Command validation only; not a Docker API write gate
  max_command_output_size: 10000
  max_log_lines: 500
  command_timeout_seconds: 30      # Default plugin command timeout (per-tool timeout wins)
  rate_limit_max_calls: 60         # Calls per tool per sliding window
  rate_limit_window_seconds: 60    # Window duration in seconds
  allowed_hosts: [localhost]      # Add names from hosts: to permit remote calls

# Multi-host: named remote targets for SSH-based diagnostics.
hosts: {}
# hosts:
#   web-1:
#     host: 10.130.0.23
#     port: 22
#     username: user
#     key_file: ~/.ssh/id_rsa
#     password: null                 # prefer env
#     host_key_policy: reject        # reject | warning | auto_add
#     known_hosts: null

plugins:
  enabled:
    - linux
    - nginx
    - docker
    - postgres
    - redis
    - systemd
    - netdiag
    - kubernetes
    - prometheus
    - loki

  postgres:
    host: "localhost"
    port: 5432
    password: "${POSTGRES_PASSWORD:-}" # From process environment; empty if absent
    # SSL/TLS modes: disable | allow | prefer | require | verify-ca | verify-full
    # verify-full is recommended for production (verifies CA + hostname)
    ssl_mode: "prefer"

  redis:
    host: "localhost"
    port: 6379
    password: "${REDIS_PASSWORD:-}" # From process environment; empty if absent

  nginx:
    log_path: "/var/log/nginx"
    stub_status_url: null # e.g. "http://127.0.0.1/nginx_status" — enables nginx_stub_status tool

  kubernetes:
    namespace: "default"
```

---

## Tools

### Linux Plugin (8 tools)
- `linux_host_stats` — Host statistics: CPU, memory, disk, load
- `linux_processes` — List of running processes
- `linux_logs` — Read system logs (journalctl, syslog)
- `linux_network` — Network interfaces, ports, connections
- `linux_firewall` — Firewall snapshot: nftables + policy routing (read-only)
- `linux_disk` — Disk and filesystem usage
- `linux_memory` — Detailed memory usage information
- `linux_execute_command` — Execute an arbitrary read-only command

### Nginx Plugin (5 tools)
- `nginx_status` — Nginx service status and processes
- `nginx_logs` — Read error and access logs
- `nginx_config` — Nginx configuration check
- `nginx_upstream` — Upstream servers: config + real HTTP health check
- `nginx_stub_status` — stub_status metrics: active connections, requests

### Docker Plugin (7 tools)
- `docker_containers` — List containers with filtering
- `docker_logs` — Container logs
- `docker_stats` — Container stats: CPU, memory, network
- `docker_info` — Full container or system info
- `docker_events` — Docker events
- `docker_system_df` — Docker disk usage
- `docker_prune` — Preview stopped containers (dry-run by default); deletion requires both `execute=true` and `confirm=true`

### PostgreSQL Plugin (7 tools)
- `pg_connections` — Active connections
- `pg_locks` — Locks and blocked queries
- `pg_slow_queries` — Slow queries
- `pg_activity` — Full activity: current queries, states, waits
- `pg_stats` — Statistics: tables, indexes, databases
- `pg_replication` — Replication status (if configured)
- `pg_tables` — List of tables with sizes and stats

### Redis Plugin (5 tools)
- `redis_ping` — Redis availability (PING)
- `redis_info` — INFO sections: memory, clients, stats, replication
- `redis_clients` — Client connections (CLIENT LIST)
- `redis_slowlog` — Slow log (SLOWLOG GET)
- `redis_memory` — Memory analysis: used, peak, fragmentation, evictions

### Systemd Plugin (5 tools)
- `service_status` — Unit status (systemctl status/is-active)
- `failed_units` — Failed units list
- `service_logs` — Service logs via journalctl -u
- `boot_analysis` — Boot time analysis (systemd-analyze blame)
- `service_ip_filter` — Effective IP filter: unit files + eBPF/bpftool (ground truth)

### Netdiag Plugin (6 tools)
- `http_check` — HTTP(S) check: status, timings, redirects
- `tls_check` — TLS certificate: expiry, chain, issuer
- `dns_resolve` — DNS resolution A/AAAA
- `tcp_connect` — TCP connect with timing
- `tcp_connect_as` — TCP probe as service user, per-uid filters (requires privileged_tools)
- `tcpdump_probe` — Short tcpdump slice (requires privileged_tools)

### Kubernetes Plugin (6 tools)
- `k8s_pods` — Pods with phases and restarts
- `k8s_events` — Cluster/namespace events
- `k8s_logs` — Pod logs (kubectl logs)
- `k8s_describe` — Pod describe (conditions)
- `k8s_top` — Pod resources (kubectl top)
- `k8s_deployments` — Deployment status

### Prometheus Plugin (4 tools)
- `prom_query` — Instant PromQL query
- `prom_range` — Range query over period
- `prom_alerts` — Firing/pending alerts
- `prom_targets` — Scrape targets up/down

### Loki Plugin (3 tools)
- `log_search` — LogQL search over period
- `log_labels` — Label names/values
- `log_tail` — Recent lines by selector

### System Tools
- `system_health_check` — Health check of all plugins
- `get_diagnostic_context` — Full diagnostic context
- `get_summary` — Brief system status summary
- `get_config` — Get current server configuration

    kubeconfig: null      # null = ~/.kube/config
    context: null         # null = current-context

  prometheus:

---

### Linux Plugin
- `linux_host_stats`
- `linux_processes`
- `linux_logs`
- `linux_network`
- `linux_firewall` — Firewall snapshot: nftables + policy routing (read-only)
- `linux_disk`
- `linux_memory`
- `linux_execute_command`

### Nginx Plugin
- `nginx_status`
- `nginx_logs`
- `nginx_config`
- `nginx_upstream`
- `nginx_stub_status`

### Docker Plugin
- `docker_containers`
- `docker_logs`
- `docker_stats`
- `docker_info`
- `docker_events`
- `docker_system_df`
- `docker_prune`

### PostgreSQL Plugin
- `pg_connections`
- `pg_locks`
- `pg_slow_queries`
- `pg_activity`
- `pg_stats`
- `pg_replication`
- `pg_tables`

### Redis Plugin
- `redis_ping`
- `redis_info`
- `redis_clients`
- `redis_slowlog` — Slow log (SLOWLOG GET)
- `redis_memory`

### Systemd Plugin
- `service_status`
- `failed_units`
- `service_logs`
- `boot_analysis`
- `service_ip_filter`

### Netdiag Plugin
- `http_check`
- `tls_check`
- `dns_resolve`
- `tcp_connect`
- `tcp_connect_as`
- `tcpdump_probe`

### Kubernetes Plugin
- `k8s_pods`
- `k8s_events`
- `k8s_logs`
- `k8s_describe`
- `k8s_top`
- `k8s_deployments`

### Prometheus Plugin
- `prom_query`
- `prom_range`
- `prom_alerts`
- `prom_targets`

### Loki Plugin
- `log_search`
- `log_labels`
- `log_tail`

---

## Architecture

```
mcp-linx/
├── src/mcp_linx/
│   ├── main.py               # MCP server entry point (FastMCP + AgentLoop)
│   ├── harness/              # Harness core: agent_loop, plugin_manager (auto-discovery),
│   │                         #   sandbox, context (compaction)
│   ├── multihost.py          # HostRegistry — named remote hosts (`hosts:` config)
│   ├── context_aggregator.py # Cross-component correlations
│   ├── security.py           # SecurityGuard (command validation, readonly mode)
│   ├── types.py              # Status, ToolResult, ComponentState, Correlation
│   ├── adapters/
│   │   ├── base.py           # Base adapter (abstract) + LocalAdapter
│   │   ├── ssh.py            # SSH adapter (paramiko)
│   │   ├── ssh_pool.py       # SSHConnectionPool + RemoteHostAdapter (multi-host)
│   │   └── docker.py         # Docker API adapter
│   └── plugins/              # Auto-discovered plugins (10 total, 56 tools)
│       ├── base.py           # DiagnosticPlugin base class (+ `host` resolution)
│       ├── linux/            # 8 tools
│       ├── nginx/            # 5 tools
│       ├── docker/           # 7 tools
│       ├── postgres/         # 7 tools
│       ├── redis/            # 5 tools
│       ├── systemd/          # 5 tools
│       ├── netdiag/          # 6 tools
│       ├── kubernetes/       # 6 tools
│       ├── prometheus/       # 4 tools
│       └── loki/             # 3 tools
├── config/settings.yaml      # Server configuration
├── tests/                    # Unit + integration tests; see Testing below
├── REMOTE_TROUBLESHOOTING.md   # Remote/SSH roadmap
└── docs/                     # ARCHITECTURE.md, DEVELOPMENT.md, SKILLS.md,
                              #   INCIDENT_504.md, skills/
```

Key features:
- **Harness ideology**: diagnostic plugins are auto-discovered from `src/mcp_linx/plugins/`; agent loops, sandboxes and context compactors are separate harness components.
- **Security**: readonly mode blocks write commands (rm, mkfs, dd, fork bombs, etc.)
- **Context Aggregator**: detects cross-component correlations
- **Adapters**: Local subprocess, SSH (paramiko), Docker API
- **Multi-host**: named remote targets in `hosts:`; `linux_*`, `nginx_*` (except `nginx_stub_status`) and `systemd_*` accept a `host` argument — see `REMOTE_TROUBLESHOOTING.md`

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/unit/test_security.py -v
pytest tests/unit/test_new_plugins.py -v
```

---

## Security

Rate limiting applies to plugin tool handlers only; the three system tools
(`get_diagnostic_context`, `get_summary`, `system_health_check`) are registered
separately and are not rate limited. Rejected calls are not audited.

SecurityGuard provides:
- **Read-only mode**: Command validation blocks write commands (rm, write, mkfs, dd
  and others) for command-executing adapters and tools. This is not a blanket
  enforcement for every state-changing operation: non-command paths, such as
  Docker prune, do not consult `readonly` and rely on their own `confirm` gate.
- **Dangerous command blocking**: rm -rf /, mkfs, dd if=/dev/zero, fork bombs etc.
- **Output size limiting**: Truncates large command outputs
- **Log line limiting**: Maximum number of log lines returned
- **Host validation**: Linux, Nginx and Systemd validate an explicit `host`
  against `security.allowed_hosts` before resolving the adapter. These are registry
  names, not destination IPs; define them in `hosts:` and include them in the allowlist.
  An empty allowlist disables this restriction. This is not a universal network ACL
  for API clients or probe destinations.
- **Input validation**: MCP handlers accept a `params` dictionary; field checks are
  implemented by individual tools, not dedicated Pydantic schemas for every tool.

---

## Context Aggregator

ContextAggregator analyzes states of all components and detects correlations:
- **Docker + Nginx**: If Docker containers are down, Nginx may have no upstreams
- **PostgreSQL + Docker**: If PostgreSQL is in a container and failing
- **Linux + components**: If Linux is in critical state, other components may fail
- **OOM events**: Linux OOM messages may explain container crashes
- **Redis + PostgreSQL**: Redis evictions while PG is slow — cache-miss cascade
- **Linux + Kubernetes**: Pods OOMKilled while host has memory pressure
- **Netdiag + Nginx**: TLS certificate issue while Nginx is failing

---

## License
MIT is declared in package metadata. A standalone `LICENSE` file is still missing;
license text and copyright attribution remain pending (TODO C1).
