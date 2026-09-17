# MCP-Linx Architecture

## Overview

MCP-Linx is an MCP server for Linux infrastructure diagnostics following the **Harness ideology**: "Everything is a plugin".

## Harness Principles

1. **Everything is a plugin** — tools, sandboxes, agent loop, context compaction
2. **Config-driven** — change components via config without code changes
3. **Auto-discovery** — plugins discovered automatically
4. **Standardized interfaces** — all plugins implement common base classes

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        MCP Client                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      MCP Server (FastMCP)                   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                   Agent Loop (Plugin)                 │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │  │
│  │  │   Default   │  │  Streaming  │  │   Custom    │  │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  │  │
│  └───────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              Plugin Manager (Auto-Discovery)          │  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐    │  │
│  │  │  Linux  │ │  Nginx  │ │ Docker  │ │ Postgres│    │  │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘    │  │
│  └───────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                   Adapters (Plugins)                  │  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐                │  │
│  │  │  Local  │ │   SSH   │ │ Docker  │                │  │
│  │  └─────────┘ └─────────┘ └─────────┘                │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Plugin Structure

```
plugins/
└── plugin_name/
    ├── __init__.py      # Plugin class (extends DiagnosticPlugin)
    └── tools.py         # Tool functions
```

## Plugin Interface

```python
class DiagnosticPlugin(ABC):
    id: str = ""  # Unique identifier
    name: str = ""  # Display name
    description: str = ""  # Plugin description

    @abstractmethod
    async def initialize(self, config: PluginConfig) -> None: ...
    @abstractmethod
    async def health_check(self) -> HealthStatus: ...
    @abstractmethod
    async def destroy(self) -> None: ...
    def get_tools(self) -> list[PluginTool]: ...
```

## Component Overview

| Component | Type | Description |
|-----------|------|-------------|
| `AgentLoop` | Plugin | Controls MCP server operation |
| `PluginManager` | Core | Auto-discovers and manages plugins |
| `Sandbox` | Plugin | Isolated execution environment |
| `ContextCompactor` | Plugin | Manages conversation history |
| `Adapter` | Plugin | Connectivity to environments |

## Available Plugins

### Agent Loops
- `default` — Standard MCP server
- `streaming` — Currently uses the same `mcp.run_async()` path as `default`;
  no additional streaming-response implementation is provided by this class.

### Adapters
- `LocalAdapter` — Local subprocess execution
- `SSHAdapter` — Remote SSH (paramiko)
- `DockerAdapter` — Docker API
- `RemoteHostAdapter` — SSH execution to a named remote host (same command interface as the local adapter)
- `SSHConnectionPool` — persistent, reusable paramiko clients keyed by host

### Multi-Host
- `HostRegistry` (`src/mcp_linx/multihost.py`) reads the `hosts:` section of `config/settings.yaml`
- `agent_loop` injects the registry into every plugin (`plugin.hosts`) at startup and closes all connections on shutdown (`HostRegistry.close_all()`)
- Tools of `linux`, `nginx` (except `nginx_stub_status`) and `systemd` accept a `host` argument (a registry name) and route the command through `_resolve_adapter(host)`; omitting `host` uses the plugin's primary adapter

### Sandboxes
- `LocalSandbox` — Local execution
- `DockerSandbox` — Docker container isolation
- `RemoteSandbox` — SSH remote host

### Context Compactors
- `SlidingWindowCompactor` — Keep last N messages
- `TokenLimitCompactor` — Limit by token count
- `SummaryCompactor` — Summarize old messages

## Configuration

Server name and loop selection use `MCP_SERVER_NAME` and `AGENT_LOOP` in the
process environment or server `.env`, not top-level YAML keys. See
[Environment and configuration](DEVELOPMENT.md#environment-and-configuration).
`plugins.enabled` selects initialization only: tools and health checks currently
include all loaded plugins. It is not an access-control boundary.

```yaml
security:
  readonly: true
  max_command_output_size: 10000
  max_log_lines: 500
  command_timeout_seconds: 30      # Дефолт таймаутов команд плагинов (per-tool перекрывает)

# Multi-host: named remote targets for SSH-based diagnostics.
hosts: {}
# hosts:
#   web-1:
#     host: 10.130.0.23
#     port: 22
#     username: user
#     key_file: ~/.ssh/id_rsa
#     host_key_policy: reject   # reject | warning | auto_add
#     known_hosts: null

plugins:
  enabled: [linux, nginx, docker, postgres]
  linux:
    ssh:
      host: null  # null = localhost
  docker:
    host: "unix:///var/run/docker.sock"
  postgres:
    host: "localhost"
    port: 5432
```

## Extension Points

| Extension | How to Create |
|-----------|---------------|
| New Plugin | Create `src/mcp_linx/plugins/my_plugin/` with `__init__.py` and `tools.py` |
| New Adapter | Extend `BaseAdapter`, implement required methods |
| New Agent Loop | Extend `AgentLoop`, register in `get_agent_loop()` |
| New Sandbox | Extend `Sandbox`, implement `execute()` and `is_available()` |

## Security

- **Read-only mode** — command-level validation: `SecurityGuard.validate_command`
  rejects write commands for command-executing adapters and tools
  (`linux_execute_command`, privileged probes). This is not a blanket blocking of
  every state-changing operation: non-command paths such as Docker prune do not
  consult `readonly` and rely on their own `confirm` gate.
- **Command validation** — whitelist + dangerous pattern detection
- **Output limiting** — prevents memory exhaustion
- **Host validation** — allowlist for remote hosts

## Deployment

```bash
# Local
python -m mcp_linx.main

# With MCP Inspector
npx @modelcontextprotocol/inspector python -m mcp_linx.main
```
