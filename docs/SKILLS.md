# Skills Documentation

## Overview

Skills in MCP-Linx follow the **Harness ideology**: skills are plugins that can be loaded, combined, and swapped via configuration.

## What is a Skill?

A **skill** is a reusable capability combining:
- **Tools** — MCP tools for specific operations
- **Knowledge** — domain-specific information
- **Workflows** — common operation patterns

## Available Skills

### Linux Diagnostics (7 tools)

| Tool | Description |
|------|-------------|
| `linux_host_stats` | Host statistics (CPU, memory, load) |
| `linux_processes` | Running processes |
| `linux_logs` | System logs |
| `linux_network` | Network interfaces |
| `linux_disk` | Disk usage |
| `linux_memory` | Memory details |
| `linux_execute_command` | Execute read-only commands |

### Nginx Diagnostics (4 tools)

| Tool | Description |
|------|-------------|
| `nginx_status` | Service status |
| `nginx_logs` | Error/access logs |
| `nginx_config` | Configuration check |
| `nginx_upstream` | Upstream servers |

### Docker Diagnostics (7 tools)

| Tool | Description |
|------|-------------|
| `docker_containers` | List containers |
| `docker_logs` | Container logs |
| `docker_stats` | Resource usage |
| `docker_info` | Container/system info |
| `docker_events` | Docker events |
| `docker_system_df` | Disk usage |
| `docker_prune` | Remove stopped containers |

### PostgreSQL Diagnostics (7 tools)

| Tool | Description |
|------|-------------|
| `pg_connections` | Active connections |
| `pg_locks` | Lock information |
| `pg_slow_queries` | Slow query log |
| `pg_activity` | Full activity |
| `pg_stats` | Database statistics |
| `pg_replication` | Replication status |
| `pg_tables` | Table information |

## System Tools

| Tool | Description |
|------|-------------|
| `get_diagnostic_context` | Full diagnostic context with correlations |
| `get_summary` | Status summary |
| `system_health_check` | Health check all plugins |

## New Skills (v1.1)

### Redis Cache (5 tools)

| Tool | Description |
|------|-------------|
| `redis_ping` | Availability check (PING) |
| `redis_info` | INFO sections: memory, clients, stats, replication |
| `redis_clients` | Client connections (CLIENT LIST) |
| `redis_slowlog` | Slow log (SLOWLOG GET) |
| `redis_memory` | Memory: used, peak, fragmentation, evictions |

### Systemd Services (4 tools)

| Tool | Description |
|------|-------------|
| `service_status` | Unit status (systemctl status/is-active) |
| `failed_units` | Failed units list |
| `service_logs` | Service logs via journalctl -u |
| `boot_analysis` | Boot time analysis (systemd-analyze blame) |

### Netdiag (4 tools)

| Tool | Description |
|------|-------------|
| `http_check` | HTTP(S) check: status, timings, redirects |
| `tls_check` | TLS certificate: expiry, chain, issuer |
| `dns_resolve` | DNS resolution A/AAAA |
| `tcp_connect` | TCP connect with timing |

### Kubernetes (6 tools)

| Tool | Description |
|------|-------------|
| `k8s_pods` | Pods with phases and restarts |
| `k8s_events` | Cluster/namespace events |
| `k8s_logs` | Pod logs (kubectl logs) |
| `k8s_describe` | Pod describe (conditions) |
| `k8s_top` | Pod resources (kubectl top) |
| `k8s_deployments` | Deployment status |

### Prometheus Metrics (4 tools)

| Tool | Description |
|------|-------------|
| `prom_query` | Instant PromQL query |
| `prom_range` | Range query over period |
| `prom_alerts` | Firing/pending alerts |
| `prom_targets` | Scrape targets up/down |

### Loki Logs (3 tools)

| Tool | Description |
|------|-------------|
| `log_search` | LogQL search over period |
| `log_labels` | Label names/values |
| `log_tail` | Recent lines by selector |

## Common Workflows

### Performance Issue
```
linux_host_stats → linux_processes → linux_memory
```

### Website Slow
```
nginx_logs(error) → docker_stats → pg_slow_queries
```

### Container Down
```
docker_containers → docker_logs → docker_events
```

### Database Issues
```
pg_slow_queries → pg_activity → pg_locks
```

### Cache Issues
```
redis_memory → redis_slowlog → redis_clients → pg_slow_queries
```

### Website Down
```
http_check → tls_check → nginx_logs → docker_containers
```

### K8s Pod CrashLoop
```
k8s_pods → k8s_events → k8s_logs → k8s_describe
```

### Alerts Firing
```
prom_alerts → prom_targets → prom_query → linux_host_stats
```

### Log Investigation
```
log_labels → log_search → log_tail → docker_logs
```

## Correlation Engine

| Correlation | Trigger |
|-------------|---------|
| Docker + Nginx | Docker down, Nginx critical |
| Linux + Docker | Linux critical, Docker degraded |
| PG + Docker | PG degraded, Docker healthy |
| Redis + PG | Redis evictions, PG degraded (cache-miss cascade) |
| Linux + K8s | K8s CrashLoop/OOMKilled, host memory pressure |
| Netdiag + Nginx | TLS cert issue, Nginx failing |

## Creating Custom Skills

### 1. Create Plugin

```bash
mkdir -p plugins/my_skill
touch plugins/my_skill/__init__.py
touch plugins/my_skill/tools.py
```

### 2. Define Plugin

```python
# plugins/my_skill/__init__.py
from mcp_linx.plugins.base import DiagnosticPlugin, PluginTool
from mcp_linx.types import HealthStatus, PluginConfig, Status

class MySkillPlugin(DiagnosticPlugin):
    id = "my_skill"
    name = "My Skill"
    description = "Custom skill"

    def get_tools(self) -> list[PluginTool]:
        from .tools import my_tool
        return [PluginTool("my_tool", "Description", my_tool)]

    async def initialize(self, config: PluginConfig) -> None:
        self._config = config

    async def health_check(self) -> HealthStatus:
        return HealthStatus(Status.HEALTHY, "OK")

    async def destroy(self) -> None:
        pass
```

### 3. Implement Tool

```python
# plugins/my_skill/tools.py
from typing import Any
from mcp_linx.plugins.my_skill import MySkillPlugin
from mcp_linx.types import ToolResult

async def my_tool(plugin: MySkillPlugin, params: dict[str, Any]) -> ToolResult:
    try:
        return ToolResult.ok({"result": "data"})
    except Exception as e:
        return ToolResult.error(str(e))
```

### 4. Enable in Config

```yaml
plugins:
  enabled: [linux, nginx, docker, postgres, my_skill]
```

## Configuration

```yaml
plugins:
  linux:
    ssh:
      host: "server1.example.com"
      key_file: "~/.ssh/id_rsa"
  nginx:
    log_path: "/var/log/nginx"
  docker:
    host: "tcp://docker-host:2375"
  postgres:
    host: "db.example.com"
    password: "${POSTGRES_PASSWORD}"
```

## Best Practices

1. **Single Responsibility** — Each tool does one thing
2. **Idempotent** — Same input, same output
3. **Safe** — Read-only by default
4. **Fast** — Return quickly
5. **Structured Output** — Use dicts, not strings

## MCP Client Setup

### Claude Desktop / Cursor

```json
{
  "mcpServers": {
    "mcp-linx": {
      "command": "python",
      "args": ["-m", "mcp_linx.main"]
    }
  }
}
```
