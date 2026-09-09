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
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DEVELOPMENT.md
│   └── SKILLS.md
├── src/mcp_linx/
│   ├── main.py
│   ├── harness/           # Harness module
│   │   ├── agent_loop.py
│   │   ├── plugin_manager.py
│   │   ├── sandbox.py
│   │   └── context.py
│   ├── plugins/           # Diagnostic plugins
│   │   ├── base.py
│   │   ├── linux/
│   │   ├── nginx/
│   │   ├── docker/
│   │   └── postgres/
│   ├── adapters/
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
mkdir -p plugins/my_plugin
touch plugins/my_plugin/__init__.py
touch plugins/my_plugin/tools.py
```

### 2. Implement Plugin Class

```python
# plugins/my_plugin/__init__.py
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
# plugins/my_plugin/tools.py
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

Plugin is auto-discovered on startup. No registration needed!

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

```yaml
# Enable debug logging
log_level: "DEBUG"
```

```bash
# Use MCP Inspector
npx @modelcontextprotocol/inspector python -m mcp_linx.main
```

## Contributing

1. Fork repository
2. Create feature branch
3. Make changes
4. Add tests
5. Run tests: `pytest tests/ -v`
6. Submit pull request
