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
    id: str = ""           # Unique identifier
    name: str = ""         # Display name
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
- `streaming` — Streaming responses

### Adapters
- `LocalAdapter` — Local subprocess execution
- `SSHAdapter` — Remote SSH (paramiko)
- `DockerAdapter` — Docker API

### Sandboxes
- `LocalSandbox` — Local execution
- `DockerSandbox` — Docker container isolation
- `RemoteSandbox` — SSH remote host

### Context Compactors
- `SlidingWindowCompactor` — Keep last N messages
- `TokenLimitCompactor` — Limit by token count
- `SummaryCompactor` — Summarize old messages

## Configuration

```yaml
mcp_server_name: "mcp-linx"
agent_loop: "default"

security:
  readonly: true
  max_command_output_size: 10000
  max_log_lines: 500
  command_timeout_seconds: 30

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
| New Plugin | Create `plugins/my_plugin/` with `__init__.py` and `tools.py` |
| New Adapter | Extend `BaseAdapter`, implement required methods |
| New Agent Loop | Extend `AgentLoop`, register in `get_agent_loop()` |
| New Sandbox | Extend `Sandbox`, implement `execute()` and `is_available()` |

## Security

- **Read-only mode** — blocks write operations
- **Command validation** — whitelist + dangerous pattern detection
- **Output limiting** — prevents memory exhaustion
- **Host validation** — whitelist for remote hosts

## Deployment

```bash
# Local
python -m mcp_linx.main

# With MCP Inspector
npx @modelcontextprotocol/inspector python -m mcp_linx.main
```
