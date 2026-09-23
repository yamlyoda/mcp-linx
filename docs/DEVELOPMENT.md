# Development Guide

## Setup

### Prerequisites

- Python 3.11+
- pip or uv

### Installation

```bash
git clone <repository-url>
cd mcp-linx
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Project Structure

```
mcp-linx/
├── config/settings.yaml
├── REMOTE_TROUBLESHOOTING.md
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DEVELOPMENT.md
│   ├── SKILLS.md
│   ├── INCIDENT_504.md
│   └── skills/            # topic-split skills (per incident)
├── src/mcp_linx/
│   ├── main.py
│   ├── harness/           # Harness module
│   │   ├── agent_loop.py
│   │   ├── plugin_manager.py
│   │   └── context.py     # ContextCompactor library API (not wired into the server)
│   ├── plugins/           # Diagnostic plugins (base.py defines `host` resolution)
│   │   ├── base.py
│   │   ├── linux/ nginx/ docker/
│   │   ├── postgres/ redis/ systemd/
│   │   └── netdiag/ kubernetes/ prometheus/ loki/
│   ├── adapters/
│   │   ├── base.py
│   │   ├── ssh.py
│   │   ├── ssh_pool.py    # SSHConnectionPool + RemoteHostAdapter (multi-host)
│   │   └── docker.py
│   ├── multihost.py       # HostRegistry (`hosts:` config)
│   ├── security.py
│   └── types.py
├── tests/
└── pyproject.toml
```

## Running the Server

```bash
# Local
python -m mcp_linx.main

# With MCP Inspector
npx @modelcontextprotocol/inspector python -m mcp_linx.main
```

## Environment and configuration

Copy `.env.example` to `.env` in the working directory. Only these five server
settings belong in `.env`; process environment values take precedence:

| Variable | Default | Purpose |
|---|---|---|
| `MCP_SERVER_NAME` | `mcp-linx` | MCP server name |
| `MCP_SERVER_VERSION` | `1.0.0` | Advertised version |
| `CONFIG_PATH` | `config/settings.yaml` | YAML configuration path |
| `LOG_LEVEL` | `INFO` | stderr logging level |
| `AGENT_LOOP` | `default` | `default` or `streaming` |

There is no `LINX_` prefix. `PLUGINS` is not a setting. `plugins.enabled` in YAML
selects the **active plugin set**: only listed plugins are loaded, initialized,
register MCP tools, and participate in health checks (`load_plugins()` applies this
filter). An absent or empty list means all discovered plugins. Per-plugin
`enabled: true` keys were removed — they were never read. This is composition, not
an access-control boundary.
Unknown keys in `.env`, including plugin secrets and `SSH_KEY_DIR`, cause
`Settings` validation errors. Unknown process environment variables are ignored
by `Settings` but remain available to other consumers.

### Plugin secrets

`load_config()` substitutes `${VAR}` and `${VAR:-default}` from **`os.environ`**.
Reading `.env` through `Settings` does not export its values to that environment.
Supply `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `PROMETHEUS_TOKEN`, and `LOKI_TOKEN`
through the launching process or a secret manager, not through the server `.env`.
For example, in Bash (the secret is entered interactively, not in shell history):

```bash
read -r -s -p 'PostgreSQL password: ' POSTGRES_PASSWORD; printf '\n'
export POSTGRES_PASSWORD
.venv/bin/python -m mcp_linx
unset POSTGRES_PASSWORD
```

The corresponding YAML must contain `password: "${POSTGRES_PASSWORD}"`, not
`password: ""`. Defaults apply only to absent variables, not empty strings.
Missing variables without defaults produce a warning and cause the **entire YAML**
to be parsed without substitution. Expansion happens before YAML parsing, without
escaping: values must be valid in their YAML quoting context. Do not treat this
mechanism as fail-fast secret validation.

Docker does not automatically receive the host environment or the server `.env`.
After supplying secrets to the host process environment, forward the required
variables explicitly, for example:

```bash
docker compose run --rm -e POSTGRES_PASSWORD -e REDIS_PASSWORD -e PROMETHEUS_TOKEN -e LOKI_TOKEN mcp-linx
```

For `docker run`, likewise use `-e VARIABLE` for each required setting or secret.
Compose's `.env` interpolation is separate from Python's `.env` loading; the current
compose file forwards only `CONFIG_PATH` by default. Set `SSH_KEY_DIR` in the shell
for the SSH mount; do not add it to a `.env` also used by a local Python launch.

### Audit and shutdown

YAML `telemetry.audit_log` enables the audit logger. Its default destination is
`/var/log/mcp-linx/audit.log`, which is not writable in the default non-root image.
Set `telemetry.audit_log_file` to a writable path (and mount a writable directory
for persistence). File setup errors produce a stderr warning; they do not stop
the server. Rate-limit rejections currently are not recorded in the audit log.

On platforms supporting asyncio signal handlers, SIGTERM/SIGINT (including
`docker stop`) request shutdown: the server task is cancelled and its cleanup
closes plugin resources, the multi-host SSH pool and any PostgreSQL SSH tunnel.
Windows signal handling is limited; allow sufficient container stop time for cleanup.

Runtime SSH tuning lives in YAML, not in the environment: `retry_attempts` /
`retry_backoff_seconds` and the PostgreSQL tunnel (`plugins.postgres.ssh.tunnel`) are
described in README → "SSH reliability: retries and tunnels".

## Testing

```bash
# All tests
pytest tests/ -v

# Specific tests
pytest tests/unit/test_security.py -v

# With coverage
pytest tests/ --cov=src/mcp_linx --cov-report=html
```

## Creating a New Plugin

### 1. Create Directory Structure

```bash
mkdir -p src/mcp_linx/plugins/my_plugin
touch src/mcp_linx/plugins/my_plugin/__init__.py
touch src/mcp_linx/plugins/my_plugin/tools.py
```

### 2. Implement Plugin Class

```python
# src/mcp_linx/plugins/my_plugin/__init__.py
from mcp_linx.plugins.base import DiagnosticPlugin, PluginTool
from mcp_linx.types import HealthStatus, PluginConfig, Status


class MyPlugin(DiagnosticPlugin):
    id = "my_plugin"
    name = "My Plugin"
    description = "Description"

    def __init__(self):
        self._config = None

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

### 3. Implement Tool Functions

```python
# src/mcp_linx/plugins/my_plugin/tools.py
from typing import Any
from mcp_linx.plugins.my_plugin import MyPlugin
from mcp_linx.types import ToolResult


async def my_tool(plugin: MyPlugin, params: dict[str, Any]) -> ToolResult:
    try:
        return ToolResult.ok({"result": "success"})
    except Exception as e:
        return ToolResult.error(str(e))
```

### 4. Auto-Discovery

Plugin is auto-discovered on startup. Add `my_plugin` to `plugins.enabled` in YAML
to enable it alongside the existing plugins. No manual class registration is needed.

## Creating a New Adapter

```python
# adapters/my_adapter.py
from mcp_linx.adapters.base import BaseAdapter


class MyAdapter(BaseAdapter):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def ping(self) -> bool: ...
    async def execute_command(self, command: str, timeout: int = 30) -> dict: ...
```

## Creating a New Agent Loop

```python
# harness/my_agent_loop.py
from mcp_linx.harness.agent_loop import AgentLoop


class MyAgentLoop(AgentLoop):
    async def setup(self, mcp, plugin_manager, config): ...
    async def run(self, mcp, plugin_manager, config): ...
    async def shutdown(self, mcp, plugin_manager): ...
```

Register in `get_agent_loop()`:
```python
loops = {
    "default": DefaultAgentLoop,
    "my_loop": MyAgentLoop,
}
```

## Code Style

- Follow PEP 8
- Use type hints
- Use async/await for I/O
- Document public APIs

## Debugging

```bash
# Enable debug logging (YAML log_level does not configure logging)
LOG_LEVEL=DEBUG .venv/bin/python -m mcp_linx
```

```bash
# Use MCP Inspector
npx @modelcontextprotocol/inspector python -m mcp_linx.main
```

## Contributing

1. Fork repository
2. Create feature branch
3. Make changes and update affected documentation in the same PR (README EN/RU,
   configuration examples, development/security guides as applicable). Follow
   [AGENTS.md](../AGENTS.md); if no documentation change is needed, explain why.
4. Add tests and validate documented examples against the actual API/configuration
5. Run tests: `pytest tests/ -v`; report unit/integration results separately
6. Submit pull request with documentation updates (or a justified no-docs-impact note)
