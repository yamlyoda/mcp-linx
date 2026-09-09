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

## Correlation Engine

| Correlation | Trigger |
|-------------|---------|
| Docker + Nginx | Docker down, Nginx critical |
| Linux + Docker | Linux critical, Docker degraded |
| PG + Docker | PG degraded, Docker healthy |

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
